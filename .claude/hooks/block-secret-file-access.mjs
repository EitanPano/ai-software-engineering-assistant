#!/usr/bin/env node
// PreToolUse guardrail on every tool (`*`): blocks any call that names a secret file or dumps
// the environment, which `permissions.deny` cannot see inside a command string.
// - Inspected: path fields, every shell token (raw and wrapper-stripped) and the quoted
//   strings of inline code (`python -c "open('.env')"`).
// - Not inspected: a Write's `content` or a Grep `pattern`, which legitimately mention env files,
//   nor the pattern operand of a shell `grep`, `egrep`, `fgrep`, `rg`, `findstr` or
//   `select-string` (the first non-option argument, or the value of `-e`, `--regexp`, `/c:`,
//   `-Pattern`). File operands and the value of `-f`, `--file`, `/g:` stay judged, and an
//   unrecognised option before the first operand means no operand is excused.
// - An interpreter that reads its program from a heredoc (`node - <<'EOF'`) is judged on that
//   body alone, and the env-dump programs (`set`, `env`, …) are not judged inside it: it is code
//   of that language, not shell. A `cat`, `tee` or `psql` heredoc body is judged as command
//   text, since bash can run what `cat` prints. A program fed through a pipe is judged whole.
// - Secrets match as file names, so a word `secret` passes; `.env.example|sample|template` pass.
import {
  allow,
  block,
  commandLines,
  commandOf,
  commandTails,
  escapeForms,
  heredocContext,
  inlineCode,
  programName,
  readPayload,
  readsStdin,
  runtimeOf,
  segmentTokens,
  shellSegments,
  splitHeredocBodies,
  tailViews,
  tokenize,
  withoutQuotes
} from './lib/guardrail.mjs'

// File names that hold credentials.
const SECRET_NAME = [
  /^\.env(\..+)?$/i, // .env, .env.local, .env.production, …
  /\.(pem|key|p12|pfx|jks|keystore|kdbx|tfstate)$/i,
  /^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$/i,
  /^(\.npmrc|\.netrc|\.pgpass|\.git-credentials|\.htpasswd|kubeconfig)$/i,
  /^(\.pypirc|pip\.(conf|ini))$/i, // package-index credentials
  /^(credentials|secrets?)\.(json|ya?ml|toml|env|txt|properties|ini)$/i,
  /service[-_]?account.*\.json$/i
]
const SECRET_NAME_ALLOWED = /^\.env\.(example|sample|template)$/i
// Directories that only ever hold credentials.
const SECRET_DIR = /(^|[\/\\])(\.aws|\.ssh|\.gnupg|\.kube|\.docker)([\/\\]|$)/i

const PATH_FIELDS = ['file_path', 'path', 'notebook_path']
const PATH_LIST_FIELDS = ['paths', 'file_paths']
// A whole-object read of the environment, per language (see runtimeOf); reading one variable by
// name passes (`os.environ['X']`, `process.env.X`, `$ENV{X}`, `ENV.fetch('X')`, `getenv('X')`).
const ENV_DUMP = {
  python: { name: 'os.environ', pattern: /(?<!\w)environb?\b(?!\s*\[|\s*\.get\b)/ },
  node: {
    name: 'process.env',
    pattern: /\b(process|Bun|Deno)\.env\b(?!\s*[.[])|\bDeno\.env\.toObject\b/
  },
  perl: { name: '%ENV', pattern: /%ENV\b/ },
  ruby: { name: 'ENV', pattern: /\bENV\b(?!\s*(\[|\.(fetch\b|key\?|has_key\?|include\?)))/ },
  php: { name: '$_ENV', pattern: /\$_(ENV|SERVER)\b(?!\s*\[)|\bgetenv\s*\(\s*\)/ }
}

// Programs whose pattern operand is a regex, not a path; their file operands are still judged.
const SEARCH_PROGRAMS = new Set(['grep', 'egrep', 'fgrep', 'rg', 'findstr', 'select-string'])

// Options of the search programs that take a value in the next argument, and that value is not a
// file the program reads. The sets are exact: a boolean flag listed here would eat a real operand.
const VALUE_LETTERS = {
  grep: 'ABCmdD',
  rg: 'ABCmdgtT'
}
const VALUE_LONG = {
  grep: new Set([
    '--include', '--exclude', '--exclude-dir', '--label', '--context', '--max-count',
    '--after-context', '--before-context', '--binary-files', '--devices', '--directories'
  ]),
  rg: new Set([
    '--glob', '--iglob', '--type', '--type-not', '--type-add', '--context', '--max-count',
    '--after-context', '--before-context', '--max-depth', '--threads'
  ])
}
// Options whose value is a file the program reads: it stays judged as a path.
const FILE_LONG = new Set(['--file', '--exclude-from', '--ignore-file'])
const BOOLEAN_LONG = new Set([
  '--recursive', '--dereference-recursive', '--ignore-case', '--no-ignore-case', '--line-number',
  '--files-with-matches', '--files-without-match', '--count', '--invert-match', '--word-regexp',
  '--line-regexp', '--fixed-strings', '--extended-regexp', '--basic-regexp', '--perl-regexp',
  '--no-filename', '--with-filename', '--only-matching', '--quiet', '--silent', '--no-messages',
  '--null', '--text', '--color', '--colour', '--hidden', '--no-ignore', '--smart-case',
  '--follow', '--byte-offset', '--initial-tab', '--files', '--no-heading', '--heading'
])

const payload = await readPayload()
const toolInput = payload.tool_input
const tool = payload.tool_name ?? 'tool'

const namedPaths = [
  ...PATH_FIELDS.map(field => toolInput[field]),
  ...PATH_LIST_FIELDS.flatMap(field => (Array.isArray(toolInput[field]) ? toolInput[field] : []))
].filter(value => typeof value === 'string')

const blockedPath = namedPaths.find(value => isSecretPath(value.trim()))
if (blockedPath !== undefined) {
  block(`blocked ${tool} call touching a secret file: ${blockedPath}. Use .env.example instead.`)
}

const command = commandOf(payload)
if (/\[(System\.)?Environment\]::GetEnvironmentVariables?\b/i.test(command)) {
  block(`blocked ${tool} call that dumps the environment (GetEnvironmentVariables). Read one variable by name instead.`)
}
// The segments of a command string handed to a shell (`bash -c "cd x; printenv"`) count too.
const lines = commandLines(command)
// The environment-dump programs are judged only where a shell runs them, so not in the body of a
// heredoc an interpreter reads. Every body, that one included, stays in the path scan.
const shellSegmentSet = new Set(lines.flatMap(line => shellSegments(shellText(line))))
const stdinText = interpreterHeredocText(command)
for (const segment of lines.flatMap(shellSegments)) {
  const shell = shellSegmentSet.has(segment)
  // `env` and `printenv` alone dump everything; checked before wrapper stripping, which
  // would otherwise remove a bare `env` as the wrapper form `env NAME=value cmd`.
  if (shell && /^(printenv|env)(\s+-\w+)*$/i.test(segment)) {
    block(`blocked ${tool} call that dumps the environment (${segment.split(/\s/)[0]}). Read one variable by name instead.`)
  }
  // Read as written and, when there is a backslash, the way bash unescapes it
  // (`cat .\env` is `cat .env`); either reading may name a secret.
  for (const unescape of escapeForms(segment)) {
    const tokens = segmentTokens(segment, unescape)
    if (tokens.length === 0) continue
    // The wrapper-stripped tokens drop runner flags such as `--env-file`, so the raw tokens
    // are scanned too, however the command is wrapped.
    const { patterns, files } = searchOperands(programName(tokens[0]), tokens.slice(1))
    const candidates = [
      ...withoutOnce(tokens, patterns),
      ...withoutOnce(rawTokens(segment, unescape), patterns.flatMap(valueForms)),
      ...files
    ]
    if (candidates.some(token => isSecretPath(stripRedirect(token)))) {
      block(`blocked ${tool} call naming a secret file in the command. Use .env.example instead.`)
    }
    judgeProgram(tokens, shell)
    // The wrapper and runner flag tables are best effort: an unlisted flag can make its value the
    // apparent program and hide the real one (`uv run --newflag x python -c "…"`, `timeout
    // --newflag x printenv`). So every later token is judged as a program start too.
    for (const tail of commandTails(segment, unescape)) {
      for (const view of tailViews(tail, unescape)) judgeProgram(view, shell)
    }
  }
}

allow()

// Inline code, stdin code and environment dumps of one program and its arguments.
function judgeProgram(tokens, shell) {
  const program = programName(tokens[0])
  const args = tokens.slice(1)
  const runtime = runtimeOf(program)
  const code = inlineCode(program, args)
  if (code !== null && inlineNamesSecret(code)) {
    block(`blocked ${tool} call whose inline code names a secret file. Use .env.example instead.`)
  }
  // An interpreter that reads its program from stdin (`python - <<EOF`, `echo "…" | node`,
  // `python -m asyncio`) has the code in a heredoc or a pipe, which the segment split has
  // already torn apart: judge the whole command text, which fails closed, unless the program
  // reads a heredoc, whose body is then its program (see interpreterHeredocText).
  if (readsStdin(program, args)) {
    if (ENV_DUMP[runtime].pattern.test(stdinText)) {
      block(
        `blocked ${tool} call that dumps the environment (${ENV_DUMP[runtime].name} via stdin). ` +
          'Read one variable by name instead.'
      )
    }
    if (inlineNamesSecret(stdinText)) {
      block(`blocked ${tool} call whose stdin code names a secret file. Use .env.example instead.`)
    }
  }
  const dump = envDump(program, args, code, shell)
  if (dump !== null) {
    block(
      `blocked ${tool} call that dumps the environment (${dump}). ` +
        'Read one variable by name instead.'
    )
  }
}

function isSecretPath(value) {
  if (value === '' || value === '-') return false
  if (SECRET_DIR.test(value)) return true
  // poetry's repository credentials: <user config dir>/pypoetry/auth.toml.
  if (/(^|[\\/])pypoetry[\\/]auth\.toml$/i.test(value)) return true
  let base = value.split(/[\\/]/).pop() ?? ''
  // A glob such as `.env*` or `backend/.env.*` names every env file.
  if (/[*?]/.test(base)) base = base.replace(/[*?].*$/, '')
  if (base === '') return false
  if (SECRET_NAME_ALLOWED.test(base)) return false
  if (/^\.env/i.test(base)) return true
  return SECRET_NAME.some(pattern => pattern.test(base))
}

// Every token of the segment (quotes already removed, so `--env-file=".env"` is
// `--env-file=.env`), plus the value of each `--flag=value` / `NAME=value`. A token with
// whitespace is a quoted string handed to something else (inline code, a shell command); it is
// handled where it is parsed, not as a file name.
function rawTokens(segment, unescape) {
  const out = []
  for (const token of tokenize(segment, unescape)) {
    if (/\s/.test(token)) continue
    out.push(token)
    const eq = token.indexOf('=')
    if (eq > 0) out.push(token.slice(eq + 1))
  }
  return out
}

// Inline code cannot be parsed, so every quoted string in it is treated as a possible file
// name, and so is any bare word that is unmistakably a secret (`.env`, a secret directory).
// An identifier chain outside quotes (`obj.key`) is code, not a file.
function inlineNamesSecret(code) {
  const parts = code.split(/\\*["'`]/)
  return parts.some((part, index) => {
    const quoted = index % 2 === 1
    return part
      .split(/[\s()[\]{},;=:+]+/)
      .some(piece => isSecretPath(piece) && (quoted || isBareSecret(piece)))
  })
}

function isBareSecret(piece) {
  return /^\.env/i.test(piece.split(/[\\/]/).pop() ?? '') || SECRET_DIR.test(piece)
}

// Whatever follows the last redirect operator in the token is the path it targets, glued to a
// word or not (`0<.env`, `2>>.env`, `&>.env`, `>|.env`, `<>.env`, `x>.env`). `>&2` leaves `2`,
// which is no secret.
function stripRedirect(token) {
  return token.replace(/^.*[<>]/, '').replace(/^[&|]+/, '')
}

// `code` is the program's inline code (see inlineCode), or null.
function envDump(program, args, code, shell) {
  if (shell) {
    const builtin = shellEnvDump(program, args)
    if (builtin !== null) return builtin
  }
  if (['get-childitem', 'gci', 'ls', 'dir', 'get-item', 'gi'].includes(program) && args.some(arg => /^env:\\?\*?$/i.test(arg))) return 'Get-ChildItem Env:'
  // A whole-object read of the environment in inline code (`print(os.environ)`,
  // `dict(os.environ)`, `{**os.environ}`, `console.log(process.env)`, `print %ENV`).
  const runtime = runtimeOf(program)
  if (runtime === null) return null
  const dump = ENV_DUMP[runtime]
  if (code !== null && dump.pattern.test(code)) return `${dump.name} dump`
  // Python: any other argument too, a script or module that receives code as a string.
  if (runtime === 'python' && args.some(arg => !arg.startsWith('-') && dump.pattern.test(arg))) {
    return `${dump.name} dump`
  }
  return null
}

// The dump programs of a shell: they print the environment when run with nothing to act on.
function shellEnvDump(program, args) {
  if (program === 'printenv' && args.length === 0) return 'printenv'
  // `env` with only its own flags (`env -u FOO`) and no program prints the environment too.
  if (program === 'env' && args.every(arg => arg.startsWith('-'))) return 'env'
  if (program === 'set' && args.length === 0) return 'set'
  if (program === 'export' && (args.length === 0 || args.every(arg => arg === '-p'))) return 'export -p'
  if (program === 'declare' && args.length > 0 && args.every(arg => /^-[px]+$/.test(arg))) return 'declare -x'
  return null
}

// The command with the bodies of plain heredocs that an interpreter reads cut out. A body that
// is piped on, substituted, unquoted with `$(` or read by anything else (`cat`, `psql`, a shell)
// stays, since those can reach a shell.
function shellText(line) {
  const { rest, code } = splitHeredocBodies(line, (text, at) => {
    const { reader, plain } = heredocContext(text, at)
    return plain && runtimeOf(reader) !== null
  })
  return [rest, ...code].join('\n')
}

// What an interpreter that reads stdin is judged on. A command with a heredoc read by an
// interpreter and no pipe is judged on the heredoc bodies alone, so the shell words around a
// `node - <<'EOF'` do not count as its program. Any other command, a pipe above all, is judged
// whole. The other bodies are in the text too, which only judges more.
function interpreterHeredocText(text) {
  let interpreter = false
  const split = splitHeredocBodies(text, (line, at) => {
    if (runtimeOf(heredocContext(line, at).reader) !== null) interpreter = true
    return false
  })
  if (split.raw || !interpreter || withoutQuotes(split.rest).includes('|')) return text
  // The bodies stand for the program only when one reader owns stdin. A process substitution, a
  // here-string or a second stdin-reading segment has its own program outside the bodies.
  if (/<\(|>\(|<<</.test(split.rest) || stdinReaderSegments(split.rest) > 1) return text
  return split.code.join('\n')
}

// How many segments of the shell words run an interpreter that reads its program from stdin.
function stdinReaderSegments(rest) {
  let count = 0
  for (const segment of shellSegments(rest)) {
    const reads = escapeForms(segment).some(unescape => {
      const tokens = segmentTokens(segment, unescape)
      const views = [tokens, ...commandTails(segment, unescape).flatMap(t => tailViews(t, unescape))]
      return views.some(view => view.length > 0 && readsStdin(programName(view[0]), view.slice(1)))
    })
    if (reads) count += 1
  }
  return count
}

// The operands of a search program that are not file paths read by name: `patterns`, the tokens
// to leave out of the path scan (the first non-option argument, or the value of `-e`,
// `--regexp`, `/c:`), and `files`, values glued to an option that name a file (`-f.env`,
// `/g:.env`). A `-f` or `--file` value in its own argument is an ordinary token and stays judged,
// and no positional is the pattern then. An option this table does not know before the first
// positional (`--newflag x`) may have eaten a file, so no positional is excused.
function searchOperands(program, args) {
  const none = { patterns: [], files: [] }
  if (!SEARCH_PROGRAMS.has(program)) return none
  if (program === 'select-string') return { patterns: selectStringPatterns(args), files: [] }
  const kind = program === 'rg' ? 'rg' : 'grep'
  const patterns = []
  const files = []
  let explicit = false
  let unknown = false
  let positional = null
  let options = true
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i]
    const name = arg.split('=')[0]
    const glued = arg.includes('=')
    if (!options || !/^[-/]./.test(arg) || (arg[0] === '/' && program !== 'findstr')) {
      if (positional === null) positional = unknown ? '' : arg
    } else if (arg === '--') {
      options = false
    } else if (arg.startsWith('--')) {
      if (name === '--regexp') {
        explicit = true
        if (glued) patterns.push(arg)
        else if (args[i + 1] !== undefined) patterns.push(args[(i += 1)])
      } else if (FILE_LONG.has(name)) {
        if (name === '--file') explicit = true
        if (!glued) i += 1
      } else if (VALUE_LONG[kind].has(name)) {
        if (!glued) i += 1
      } else if (!BOOLEAN_LONG.has(name)) {
        unknown = true
      }
    } else if (program === 'findstr') {
      const flag = /^\/([A-Za-z])(?::(.*))?$/.exec(arg)
      if (flag === null) {
        if (positional === null) positional = unknown ? '' : arg
      } else if (/c/i.test(flag[1])) {
        explicit = true
        patterns.push(arg)
      } else if (/[gf]/i.test(flag[1])) {
        explicit = explicit || /g/i.test(flag[1])
        if (flag[2] !== undefined) files.push(flag[2])
      }
    } else {
      // A short cluster: `-rn`, `-ie`, `-A3`, `-f.env`. The first value letter ends it.
      for (let k = 1; k < arg.length; k += 1) {
        const letter = arg[k]
        const attached = arg.slice(k + 1)
        if (letter === 'e') {
          explicit = true
          if (attached !== '') patterns.push(arg)
          else if (args[i + 1] !== undefined) patterns.push(args[(i += 1)])
          break
        }
        if (letter === 'f') {
          explicit = true
          if (attached !== '') files.push(attached)
          else i += 1
          break
        }
        if (VALUE_LETTERS[kind].includes(letter)) {
          if (attached === '') i += 1
          break
        }
      }
    }
  }
  const excused = !explicit && positional !== null && positional !== ''
  return { patterns: excused ? [...patterns, positional] : patterns, files }
}

// `Select-String <pattern> -Path <file>`: the pattern is `-Pattern`'s value or the first argument.
// Any other option first may take a path, so nothing is excused then.
function selectStringPatterns(args) {
  const at = args.findIndex(arg => /^-pattern$/i.test(arg))
  if (at !== -1) return args[at + 1] === undefined ? [] : [args[at + 1]]
  return args.length > 0 && !args[0].startsWith('-') ? [args[0]] : []
}

// A token and the value after its `=`, the two forms rawTokens lists.
function valueForms(token) {
  const eq = token.indexOf('=')
  return eq > 0 ? [token, token.slice(eq + 1)] : [token]
}

// `list` without one occurrence of each of `values`: a pattern equal to a file operand
// (`grep PATTERN PATTERN`) excuses the pattern only.
function withoutOnce(list, values) {
  const out = [...list]
  for (const value of values) {
    const at = out.indexOf(value)
    if (at !== -1) out.splice(at, 1)
  }
  return out
}
