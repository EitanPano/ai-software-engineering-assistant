#!/usr/bin/env node
// PreToolUse guardrail on Bash|PowerShell: blocks destructive commands in every permission mode.
// - Rules match the program and its flags after wrappers, runners and container exec are
//   peeled, so `echo "rm -r x"` passes and `docker compose exec db psql …` is a psql call.
// - Database text rules (SQL, redis, mongosh) apply only when that client is in the command.
//   Script files handed to a client (`psql -f x.sql`) are not inspected.
// - `permissions.deny` in settings.json is a separate layer; secret files are
//   block-secret-file-access.mjs.
import {
  allow,
  block,
  commandLines,
  commandOf,
  commandTails,
  escapeForms,
  programName,
  readPayload,
  segmentTokens,
  shellSegments,
  tailViews
} from './lib/guardrail.mjs'

const SQL_CLIENTS = new Set([
  'psql', 'pgcli', 'mysql', 'mariadb', 'sqlite3', 'sqlcmd', 'clickhouse-client', 'cockroach', 'usql',
  'cqlsh', 'duckdb', 'sqlplus'
])
const REDIS_CLIENTS = new Set(['redis-cli', 'valkey-cli'])
const MONGO_CLIENTS = new Set(['mongosh', 'mongo'])
// Programs that run a program inside a container, after `exec` or `run`. Their flag tables are
// not modelled: every token after the subcommand is judged as a program start instead.
const CONTAINER_RUNTIMES = new Set(['docker', 'docker-compose', 'podman', 'nerdctl', 'kubectl'])

// mongosh spellings that drop a database or collection, or write with an empty filter (every
// document). Quote runs allow backslashes because quotes may arrive escaped (`\"drop\"`).
const QUOTES = '[\\\\"\'`]*'
const MONGO_RULES = [
  [new RegExp(`\\bdropDatabase\\b${QUOTES}\\s*[(:]`), 'dropDatabase'],
  [/\.\s*drop\s*\(/, 'collection.drop()'],
  [/\bdropCollection\s*\(/, 'dropCollection()'],
  [new RegExp(`[{,\\s]${QUOTES}drop${QUOTES}\\s*:`), '{ drop: … } command'],
  [/\b(deleteMany|remove)\s*\(\s*(\{\s*\}\s*)?[,)]/, 'deleteMany|remove with an empty filter'],
  [/\b(updateMany|replaceOne)\s*\(\s*\{\s*\}\s*,/, 'updateMany|replaceOne with an empty filter']
]

const payload = await readPayload()
const command = commandOf(payload)

// Each segment, those of a command string handed to a shell included, is read twice when it has
// a backslash: as written and the way bash unescapes it (`rm \-rf x` is `rm -rf x`); either
// reading may trigger a rule.
const segments = commandLines(command).flatMap(shellSegments).flatMap(segment =>
  escapeForms(segment).map(unescape => ({
    segment,
    unescape,
    tokens: segmentTokens(segment, unescape)
  }))
)
// Every program judged, wherever it stood: first in a segment, behind a wrapper or package
// runner, or inside a container. The database text rules below key on it.
const programs = new Set()

for (const { segment, unescape, tokens } of segments) {
  if (tokens.length === 0) continue
  judge(tokens)
  // The wrapper and runner flag tables are best effort: an unlisted value flag would make its
  // value the "program" and hide the real one. So judge every token after a wrapper or runner
  // as a program start too (`uv run --newflag x rm -rf y`), which fails closed.
  for (const tail of commandTails(segment, unescape)) judgeTail(tail, unescape)
  const inner = containerTail(programName(tokens[0]), tokens.slice(1))
  if (inner !== null) judgeTail(inner, unescape)
}

// SQL travels through pipes and -c flags: when an SQL client appears anywhere, judge the
// whole command text, and each statement of it for the clauses that scope a write.
const upper = command.toUpperCase()
if ([...programs].some(program => SQL_CLIENTS.has(program))) {
  if (/\bDROP\s+(TABLE|DATABASE|SCHEMA|KEYSPACE)\b/.test(upper)) refuse('DROP TABLE|DATABASE|SCHEMA|KEYSPACE', 'sql client')
  if (/\bTRUNCATE\s+\S+/.test(upper)) refuse('TRUNCATE', 'sql client')
  for (const statement of sqlStatements(command)) {
    if (/\bWHERE\b/.test(statement)) continue
    if (/\bDELETE\s+((LOW_PRIORITY|QUICK|IGNORE)\s+)*FROM\b/.test(statement)) refuse('DELETE without WHERE', 'sql client')
    // `ON UPDATE SET NULL`, `DO UPDATE SET` (upsert) and `THEN UPDATE SET` (merge) are not
    // mass updates.
    if (/(?<!\b(ON|DO|THEN)\s+)\bUPDATE\s+[\s\S]*?\bSET\b/.test(statement)) refuse('UPDATE without WHERE', 'sql client')
  }
}
if ([...programs].some(program => REDIS_CLIENTS.has(program)) && /\bFLUSH(ALL|DB)\b/.test(upper)) {
  refuse('redis FLUSHALL|FLUSHDB', 'redis-cli')
}
if ([...programs].some(program => MONGO_CLIENTS.has(program))) {
  for (const [pattern, rule] of MONGO_RULES) {
    if (pattern.test(command)) refuse(`mongosh ${rule}`, 'mongosh')
  }
}

allow()

function judge(tokens) {
  const program = programName(tokens[0])
  programs.add(program)
  const hit = findRule(program, tokens.slice(1))
  if (hit !== null) refuse(hit, program)
}

function judgeTail(tail, unescape) {
  for (const view of tailViews(tail, unescape)) judge(view)
}

// The tokens after a container runtime's `exec` or `run`, or null when it runs nothing inside
// a container.
function containerTail(program, args) {
  if (!CONTAINER_RUNTIMES.has(program)) return null
  const at = args.findIndex(arg => /^(exec|run)$/i.test(arg))
  return at === -1 ? null : args.slice(at + 1)
}

// Upper-cased SQL statements, split at `;` and at quote boundaries (each `-c` value stands
// alone), so a WHERE in one never excuses a DELETE or UPDATE in another.
function sqlStatements(text) {
  const statements = []
  let current = ''
  let quote = null
  const flush = () => {
    if (current.trim() !== '') statements.push(current.toUpperCase())
    current = ''
  }
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if ((char === '\\' || char === '`') && i + 1 < text.length) {
      current += char + text[i + 1]
      i += 1
    } else if (char === ';') {
      flush()
    } else if (quote === null && (char === '"' || char === "'")) {
      flush()
      quote = char
    } else if (char === quote) {
      flush()
      quote = null
    } else {
      current += char
    }
  }
  flush()
  return statements
}

function refuse(rule, program) {
  // Never echo the full command: it can carry a token or URL, and stderr lands in the
  // transcript. The program name is safe only when it is a bare word.
  block(
    `blocked destructive command: ${rule} (program: ${/^[\w.-]+$/.test(program) ? program : 'not shown'}). ` +
      'Agents do not run this; ask the user to run it by hand.'
  )
}

function findRule(program, args) {
  const flags = args.filter(arg => arg.startsWith('-') || arg.startsWith('/'))
  const words = args.map(arg => arg.toLowerCase())

  // Recursive deletion, any spelling: rm -r, rm -fr, rm -R -f, rm --recursive, find -delete,
  // rmdir /s, Remove-Item -Recurse and its aliases, rimraf.
  if (program === 'rm' && flags.some(flag => /^-[a-z]*r/i.test(flag) || flag === '--recursive')) return 'recursive rm'
  if (program === 'rm' && flags.some(flag => /^-r(ec(urse)?)?$/i.test(flag))) return 'recursive rm'
  if (program === 'find') {
    if (words.includes('-delete')) return 'find -delete'
    const exec = args.findIndex(arg => /^-exec(dir)?$/.test(arg))
    if (exec >= 0 && args.length > exec + 1) {
      const inner = findRule(programName(args[exec + 1]), args.slice(exec + 2))
      if (inner !== null) return `find -exec ${inner}`
    }
  }
  if (['rmdir', 'rd', 'del', 'erase'].includes(program) && flags.some(flag => /^\/s$/i.test(flag))) return 'recursive delete'
  if (['remove-item', 'ri', 'del', 'erase', 'rd', 'rmdir'].includes(program) && flags.some(flag => /^-r(ec(urse)?)?$/i.test(flag))) return 'Remove-Item -Recurse'
  if (program === 'rimraf') return 'rimraf'

  // Git history or working-tree destruction.
  if (program === 'git') {
    const sub = words[0]
    if (sub === 'push' && (flags.some(flag => /^(-f|--force)/i.test(flag)) || words.some(word => /^\+\S+/.test(word)))) return 'git push --force (with or without a lease)'
    if (sub === 'reset' && words.includes('--hard')) return 'git reset --hard'
    if (sub === 'clean' && flags.some(flag => /^-[a-z]*f/i.test(flag) || flag === '--force')) return 'git clean -f'
    if (sub === 'branch' && (args.includes('-D') || (words.includes('--delete') && words.includes('--force')))) return 'git branch -D'
    if (sub === 'stash' && (words[1] === 'drop' || words[1] === 'clear')) return 'git stash drop|clear'
    if ((sub === 'checkout' || sub === 'restore') && words.includes('.')) return 'git checkout/restore . (discards edits)'
    if (sub === 'filter-branch' || sub === 'filter-repo') return 'git history rewrite'
  }

  // Database tooling that applies or drops schema directly.
  if (program === 'drizzle-kit' && (words[0] === 'drop' || words[0] === 'push')) return 'drizzle-kit drop|push (generate + migrate instead)'
  if (program === 'prisma' && ((words[0] === 'migrate' && words[1] === 'reset') || (words[0] === 'db' && words.includes('--force-reset')))) return 'prisma reset'
  if (program === 'supabase' && words[0] === 'db' && words[1] === 'reset') return 'supabase db reset'

  // Database programs that drop a database, or drop the target before writing into it.
  if (program === 'dropdb') return 'dropdb'
  if (program === 'mysqladmin' && words.includes('drop')) return 'mysqladmin drop'
  if ((program === 'mongorestore' || program === 'mongoimport') && flags.some(flag => /^--drop(=|$)/i.test(flag))) return `${program} --drop`
  if (program === 'pg_restore' && flags.some(flag => flag === '--clean' || /^-[A-Za-z]*c/.test(flag))) return 'pg_restore --clean (drops objects first)'

  // Container and volume destruction (docker and the docker-compose v1 spelling).
  const dockerWords = program === 'docker-compose' ? ['compose', ...words] : words
  if (program === 'docker' || program === 'docker-compose') {
    if (dockerWords[0] === 'system' && dockerWords[1] === 'prune') return 'docker system prune'
    if (dockerWords[0] === 'volume' && (dockerWords[1] === 'rm' || dockerWords[1] === 'prune')) return 'docker volume rm|prune'
    if (dockerWords[0] === 'compose' && dockerWords.includes('down') && flags.some(flag => /^-[a-z]*v/i.test(flag) || flag === '--volumes')) return 'docker compose down -v (drops the database volume)'
  }

  return null
}
