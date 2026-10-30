// Shared code of the PreToolUse guardrail hooks: payload I/O, path helpers and shell parsing.
// The hooks fail closed:
// - exit 0 allows, exit 2 blocks with the reason on stderr; an unreadable payload blocks.
// - readPayload() makes a crash after parsing block. A crash before it (a syntax error) is
//   covered by `onFailure: "block"` in .claude/settings.json.
import path from 'node:path'
import process from 'node:process'

export function block(message) {
  console.error(`[guardrail] ${message}`)
  process.exit(2)
}

export function allow() {
  process.exit(0)
}

export async function readPayload() {
  const crash = error => block(`hook crashed, blocking by default: ${error?.message ?? error}`)
  process.on('uncaughtException', crash).on('unhandledRejection', crash)

  let input = ''
  for await (const chunk of process.stdin) input += chunk
  if (input.trim() === '') block('empty hook payload, blocking by default')

  let payload
  try {
    payload = JSON.parse(input)
  } catch {
    block('unreadable hook payload (invalid JSON), blocking by default')
  }
  if (!isPlainObject(payload)) block('hook payload is not an object, blocking by default')
  if (!isPlainObject(payload.tool_input)) {
    block('hook payload has no tool_input, blocking by default')
  }
  return payload
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// The sub-agent role, or null in the interactive session. Claude Code sends the agent's
// frontmatter `name` as `agent_type`; AGENT_ROLE in the environment is an override for a
// headless driver. `agent_type` wins when both are present.
export function resolveRole(payload) {
  const isRole = value => typeof value === 'string' && value !== ''
  return [payload.agent_type, process.env.AGENT_ROLE].find(isRole) ?? null
}

// The project root the hook should measure paths against. CLAUDE_PROJECT_DIR is set by
// Claude Code for every hook and does not move when the session runs `cd`; payload.cwd
// does, so it is only a fallback for runtimes that do not export the variable.
export function projectRoot(payload) {
  return path.resolve(process.env.CLAUDE_PROJECT_DIR ?? payload.cwd ?? process.cwd())
}

// The directory Claude Code's file tools resolve a relative path against: the session's
// current directory (payload.cwd), which a Bash `cd` moves. Null when the payload does not
// carry a usable value.
export function sessionCwd(payload) {
  const cwd = payload.cwd
  return typeof cwd === 'string' && path.isAbsolute(cwd) ? cwd : null
}

// Claude Code rewrites some spellings before opening a file (surrounding whitespace, a leading
// `~`, `/c/...` on Windows). The hooks refuse them rather than copy that unversioned logic, so
// a plain path means the same thing to both sides.
export function isCanonicalPath(rawPath) {
  if (rawPath !== rawPath.trim()) return false
  if (rawPath.startsWith('~')) return false
  if (process.platform === 'win32' && /^\/[a-zA-Z](\/|$)/.test(rawPath)) return false
  return true
}

// rawPath relative to root with forward slashes, a relative one resolved against `base` (the
// session cwd), so `frontend/../backend/x.ts` collapses first. `escapes` is true for the root
// itself or anything outside it, which no role may write.
export function toProjectRelative(rawPath, root, base = root) {
  const absolute = path.resolve(base, rawPath)
  const rel = path.relative(root, absolute).split(path.sep).join('/')
  const escapes = rel === '' || rel === '..' || rel.startsWith('../') || path.isAbsolute(rel)
  return { rel, escapes }
}

// The shell command of a payload ('' for a tool that has none). A Bash or PowerShell call
// whose command is not a string cannot be inspected, so it blocks.
export function commandOf(payload) {
  const command = payload.tool_input.command
  if (typeof command === 'string') return command
  if (payload.tool_name === 'Bash' || payload.tool_name === 'PowerShell') {
    block('shell call whose command is not a string cannot be inspected, blocking by default')
  }
  return ''
}

// Operators that start a new command, matched only outside quotes.
const SEGMENT_OPERATORS = ['&&', '||', '|', ';', '&', '\n', '\r', '$(', '`', '(', ')']

// Splits a command at operators that start a new command (&&, ||, |, ;, &, subshells),
// leaving quoted strings intact so `node -e "f(process.env)"` stays one segment.
export function shellSegments(command) {
  const segments = []
  let current = ''
  let quote = null
  for (let i = 0; i < command.length; i += 1) {
    const char = command[i]
    const next = command[i + 1] ?? ''
    // A backslash pairs with the next character inside double quotes and, outside quotes, before
    // `\`, `"` or `'`: bash reads `\"` as a literal that must not open a string, and `\\"` as one.
    const paired = quote === null ? /^[\\"']$/.test(next) : quote === '"' && next !== ''
    if (char === '\\' && paired) {
      current += char + next
      i += 1
    } else if (quote !== null) {
      if (char === quote) quote = null
      current += char
    } else if (char === '"' || char === "'") {
      // A quote after PowerShell's escaping backtick is a literal too.
      if (command[i - 1] !== '`') quote = char
      current += char
    } else {
      const operator = SEGMENT_OPERATORS.find(candidate => command.startsWith(candidate, i))
      if (operator === undefined) {
        current += char
      } else {
        segments.push(current)
        current = ''
        i += operator.length - 1
      }
    }
  }
  segments.push(current)
  return segments.map(segment => segment.trim()).filter(segment => segment !== '')
}

// `rest` is the command without the bodies it strips; `code` holds every body kept for a raw scan.
// A body is stripped only when it is terminated, is data (a quoted delimiter, or no `$(`, backtick
// or `${` in it) and `mayStrip(line, at, body)` agrees: the caller knows which program reads it.
// Quotes in a kept body do not protect a command substitution, so a caller scans it raw.
// - The scan is sequential, like bash: quote state carries across the command lines, and a body
//   is opaque (its quotes, such as an apostrophe in SQL, are never read).
// - A command with `$'`, a backslash-newline continuation (bash joins the lines before it reads an
//   operator) or a quote left open is not parsed at all: nothing is stripped, all of it is raw.
export function splitHeredocBodies(command, mayStrip = () => true) {
  const raw = { rest: '', code: [command], raw: true }
  if (command.includes("$'") || /\\\r?\n/.test(command)) return raw
  const lines = command.split('\n')
  const kept = []
  const code = []
  let quote = null
  for (let i = 0; i < lines.length; i += 1) {
    kept.push(lines[i])
    const scanned = scanQuotes(lines[i], quote)
    quote = scanned.quote
    const operators = heredocDelimiters(lines[i], scanned.blank)
    // A quote still open after an operator line would move the body past this scan's view.
    if (operators.length > 0 && quote !== null) return raw
    let next = i + 1
    for (const { word, stripTabs, quoted, at } of operators) {
      const body = []
      while (next < lines.length && !isTerminator(lines[next], word, stripTabs)) {
        body.push(lines[next])
        next += 1
      }
      const text = body.join('\n')
      const data = quoted || !/\$\(|`|\$\{/.test(text)
      // Asked even for a body that cannot be stripped, since the caller also learns from it.
      const strip = mayStrip(lines[i], at, text)
      if (!(next < lines.length && data && strip)) code.push(...body)
      next += 1
    }
    i = next - 1
  }
  return quote === null ? { rest: kept.join('\n'), code } : raw
}

// Docker and Compose `exec` flags that take a value, so it is not read as the container.
const EXEC_VALUE_FLAGS = new Set([
  '-u', '--user', '-e', '--env', '-w', '--workdir', '--env-file', '--index', '--detach-keys'
])

// The program that reads a heredoc, after leading assignments and the `docker compose exec`,
// `docker exec` and `kubectl exec … --` front ends. A flag this table misses makes a value look
// like the program, which is not `cat` or `psql`, so the body stays in the scan.
export function heredocReader(tokens) {
  let at = tokens.findIndex(token => !/^[A-Za-z_][A-Za-z0-9_]*=/.test(token))
  if (at === -1) return null
  const program = programName(tokens[at])
  if (program === 'kubectl') {
    // Whatever follows `--` is the command, so no value flag before it can shift the reader.
    const dashes = tokens.indexOf('--')
    if (dashes === -1 || !tokens.slice(at, dashes).includes('exec')) return null
    return programName(tokens[dashes + 1] ?? '')
  }
  if (program !== 'docker' && program !== 'docker-compose') return program
  at = tokens.indexOf('exec', at)
  if (at === -1) return null
  at += 1
  while (tokens[at]?.startsWith('-')) at += EXEC_VALUE_FLAGS.has(tokens[at]) ? 2 : 1
  return programName(tokens[at + 1] ?? '')
}

// What a heredoc operator at `at` in `line` hands its body to: `reader` is the program that reads
// it, and `plain` is false when the operator's output is piped on or the line substitutes a
// command before it (`eval "$(cat <<EOF …)"`), so the body may run whatever its reader is.
export function heredocContext(line, at) {
  const before = line.slice(0, at).replace(/\d?>&[\d-]+/g, ' ')
  const reader = heredocReader(tokenize(shellSegments(before).at(-1) ?? ''))
  const plain = !withoutQuotes(line.slice(at)).includes('|') && !/\$\(|`/.test(before)
  return { reader, plain }
}

// One line with its quoted text (and the quotes) replaced by spaces, same length, and the quote
// state at its end, given the state at its start. An escaped character outside quotes is kept.
function scanQuotes(line, quote) {
  let blank = ''
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    if (quote === null && char === '\\') {
      blank += line.slice(i, i + 2)
      i += 1
    } else if (quote === null && (char === '"' || char === "'")) {
      quote = char
      blank += ' '
    } else if (quote !== null) {
      if (char === quote) quote = null
      else if (char === '\\' && quote === '"') {
        blank += ' '
        i += 1
      }
      blank += ' '
    } else {
      blank += char
    }
  }
  return { blank, quote }
}

function isTerminator(line, word, stripTabs) {
  const text = line.replace(/\r$/, '')
  return (stripTabs ? text.replace(/^\t+/, '') : text) === word
}

// A delimiter word ends at a shell word boundary; anything glued to it (`<<E"O"F`, `<<X+`) is
// a different word than this scan reads, so the `<<` is not taken as a heredoc and its body
// stays in the scan.
const HEREDOC_OPERATOR =
  /^<<(-?)[ \t]*(?:\\?([A-Za-z0-9_.-]+)|'([^']*)'|"([^"]*)")(?=[\s;&|<>()]|$)/

// The heredoc operators of one line, in order, with their offsets. This must never see a heredoc
// that bash does not, since the lines it then skips would run. So it stops at a comment, skips
// arithmetic (`$((1<<2))`). `blank` is the line with quoted text blanked by blankQuotes over the
// whole command, so `echo "<<X"` and a quote opened on an earlier line hide their `<<`; the
// delimiter word is read from `line`, where a quoted word is still readable.
function heredocDelimiters(line, blank) {
  const found = []
  for (let i = 0; i < blank.length; i += 1) {
    if (blank[i] === '\\') {
      i += 1
    } else if (blank[i] === '#' && (i === 0 || /[\s;&|<>()]/.test(blank[i - 1]))) {
      break
    } else if (blank.startsWith('((', i)) {
      let depth = 0
      do {
        if (blank[i] === '(') depth += 1
        else if (blank[i] === ')') depth -= 1
        i += 1
      } while (i < blank.length && depth > 0)
      i -= 1
    } else if (blank.startsWith('<<', i)) {
      if (blank[i + 2] === '<' || blank[i - 1] === '<') {
        i += 2
        continue
      }
      const match = HEREDOC_OPERATOR.exec(line.slice(i))
      if (match !== null) {
        found.push({
          word: match[2] ?? match[3] ?? match[4],
          stripTabs: match[1] === '-',
          quoted: match[2] === undefined || match[0].includes('\\'),
          at: i
        })
        i += match[0].length - 1
      } else {
        i += 1
      }
    }
  }
  return found
}

// Shell word splitting for guard purposes: quotes are removed and quoted parts join their word
// (`--flag=".env"` is `--flag=.env`); an unterminated quote runs to the end.
// - Default: backslashes stay as written, so Windows paths survive.
// - `unescape`: the bash reading, where `\x` outside quotes is `x` (see escapeForms).
export function tokenize(text, unescape = false) {
  const tokens = []
  let word = null
  let quote = null
  const append = chars => (word = (word ?? '') + chars)
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    const next = text[i + 1] ?? ''
    if (quote !== null) {
      if (char === quote) {
        quote = null
      } else if (char === '\\' && quote === '"' && next !== '') {
        append(char + next)
        i += 1
      } else {
        append(char)
      }
    } else if (char === '\\' && unescape) {
      if (next !== '') append(next)
      i += 1
    } else if (char === '\\' && /^[\\"';&|<>()$`]$/.test(next)) {
      // `\` makes a quote or operator literal (`\"` opens no string) and otherwise stays, so
      // `backend\.env` keeps its word. `\ ` still splits: over-splitting errs to blocking, and a
      // PowerShell path ending in `\` must not merge with the `-Recurse` after it.
      append(next === '\\' ? '\\\\' : next)
      i += 1
    } else if ((char === '"' || char === "'") && text[i - 1] !== '`') {
      // After PowerShell's escaping backtick a quote is literal and falls through to the word.
      quote = char
      word ??= ''
    } else if (/\s/.test(char)) {
      if (word !== null) tokens.push(word)
      word = null
    } else {
      // PowerShell reads a leading en dash, em dash or horizontal bar as `-` (`–Recurse`).
      append(word === null && /[–—―]/.test(char) ? '-' : char)
    }
  }
  if (word !== null) tokens.push(word)
  return tokens
}

// The command with quoted strings blanked, for scans that must not see string contents.
export function withoutQuotes(command) {
  // An escaped character outside quotes (`\"`) is skipped first so it cannot open a string.
  return command.replace(/\\[\s\S]|"(?:[^"\\]|\\.)*"|'[^']*'/g, match =>
    match.startsWith('\\') ? match : '""'
  )
}

// The `unescape` values a caller must judge: as written (Windows paths keep backslashes) and,
// when there is a backslash, the bash reading (`rm \-rf x` is `rm -rf x`). A command is refused
// when either reading is.
export function escapeForms(segment) {
  return segment.includes('\\') ? [false, true] : [false]
}

export function programName(token) {
  const base = token.replace(/^["']|["']$/g, '').split(/[\\/]/).pop() ?? ''
  return base.replace(/\.(exe|cmd|bat)$/i, '').toLowerCase()
}

// Programs that run another program, shells first: the real program is what follows their flags.
const WRAPPERS = new Set([
  'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'pwsh', 'powershell', 'cmd',
  'sudo', 'doas', 'env', 'nohup', 'time', 'command', 'exec', 'eval', 'xargs', 'nice', 'busybox',
  'timeout', 'stdbuf', 'caffeinate', 'npx', 'pnpx'
])
const flagSet = list => new Set(list.split(/\s+/).filter(Boolean))
const NO_FLAGS = new Set()
// The value flags of each wrapper, which consume the next token (`sudo -u root`, `timeout -s
// KILL 5`); any other flag stands alone. From the GNU coreutils and findutils, sudo, doas, bash
// and npm manuals, BSD spellings included. A flag missing here cannot hide the program from a
// caller that judges the wrapper's tail (see commandTails).
const SHELL_FLAGS = flagSet('-o -O +o +O --rcfile --init-file')
const WRAPPER_FLAGS = {
  sh: SHELL_FLAGS,
  bash: SHELL_FLAGS,
  zsh: SHELL_FLAGS,
  dash: SHELL_FLAGS,
  ksh: SHELL_FLAGS,
  sudo: flagSet(
    '-a --auth-type -c --login-class -C --close-from -D --chdir -g --group -p --prompt ' +
      '-R --chroot -r --role -t --type -T --command-timeout -U --other-user -u --user'
  ),
  doas: flagSet('-a -C -u'),
  // -S is left out: its value is a command line (see ENV_SPLIT).
  env: flagSet('-u --unset -C --chdir -P -L -U'),
  nice: flagSet('-n --adjustment'),
  timeout: flagSet('-s --signal -k --kill-after'),
  stdbuf: flagSet('-i --input -o --output -e --error'),
  time: flagSet('-f --format -o --output'),
  exec: flagSet('-a'),
  caffeinate: flagSet('-t -w'),
  xargs: flagSet(
    '-a --arg-file -d --delimiter -E -I -J -L -n --max-args -P --max-procs -R -s --max-chars ' +
      '-S --process-slot-var'
  ),
  npx: flagSet('-p --package -w --workspace --prefix'),
  pnpx: flagSet('--package')
}
// `env -S "a b"` and `--split-string=…` split their value into env's own arguments.
const ENV_SPLIT = /^(?:-S|--split-string=?)([\s\S]*)$/
// fish runs the value of -C / --init-command as a command line of its own.
const FISH_INIT = /^(?:-C|--init-command=?)([\s\S]*)$/
// cmd runs what is glued to /c or /k as well (`/c"rmdir /s x"` reads `/crmdir /s x`).
const CMD_GLUED = /^\/[ck]([\s\S]+)$/i
// powershell and pwsh parameters that take a value. Any prefix of a name is that parameter
// (`-ex Bypass`), and pwsh adds the aliases. -Command and -File take the rest of the line, so
// the command after them is what gets judged.
const POWERSHELL_VALUE_PARAMS = [
  'executionpolicy', 'workingdirectory', 'outputformat', 'inputformat', 'windowstyle',
  'configurationname', 'configurationfile', 'settingsfile', 'custompipename', 'psconsolefile',
  'version'
]
const POWERSHELL_VALUE_ALIASES = new Set(['ep', 'wd', 'o', 'of', 'if', 'w', 'v'])
const POWERSHELL_REST_PARAMS = ['command', 'file']
const POWERSHELL_ENCODED_PARAMS = ['encodedcommand', 'encodedarguments']
// timeout reads its duration with strtod, so `1e1`, `0x10` and `inf` are durations too.
const DURATION = /^(\+?\.?\d|inf)/i
// How many wrappers and runners are peeled before the program. A deeper nest is refused: an
// analysis that stopped there would let `sudo` repeated past the limit hide any command.
const MAX_WRAPPER_DEPTH = 8

// Tokens of one segment with surrounding quotes removed; leading NAME=value assignments,
// wrappers (sudo, env, timeout, bash -lc, powershell -NoProfile -Command, …) and package
// runners (bunx, npx, bun x, bun run, …) are stripped so the real program is first. A
// quoted command string handed to a shell is re-tokenised.
export function segmentTokens(segment, unescape = false) {
  return analyzeSegment(segment, unescape).tokens
}

// What follows each wrapper and package runner in the segment, flags included and unresolved.
// A flag table that is wrong or incomplete shifts the program by a token, so a caller that must
// not miss a program can look at every later token (see block-destructive-bash).
export function commandTails(segment, unescape = false) {
  return analyzeSegment(segment, unescape).tails
}

// Every later token after a wrapper or package runner that names an interpreter, analysed as
// the start of a command (the token lists, program first). The flag tables are best effort, so
// `uv run --newflag x python -c "…"` makes `x` the apparent program; a caller that judges
// inline code, stdin and the environment looks at these views too, which fails closed.
export function interpreterViews(segment, unescape = false) {
  const isInterpreter = token => runtimeOf(programName(token)) !== null
  return commandTails(segment, unescape).flatMap(tail => viewsOf(tail, unescape, isInterpreter))
}

// The command line and every command string handed to a shell inside it (`bash -c "cd x;
// rm -rf y"`, `powershell -Command "…"`), behind a tail position too. Each one is split into
// segments and judged like the line itself; a string is strictly shorter than its line, so
// this ends.
export function commandLines(command) {
  const lines = [command]
  for (let i = 0; i < lines.length; i += 1) {
    for (const segment of shellSegments(lines[i])) {
      for (const unescape of escapeForms(segment)) {
        const { scripts, tails } = analyzeSegment(segment, unescape)
        const tailScripts = tails.flatMap(tail =>
          tail.flatMap((_, at) => analyzeTokens(tail.slice(at), unescape).scripts)
        )
        for (const line of [...scripts, ...tailScripts]) {
          if (!lines.includes(line)) lines.push(line)
        }
      }
    }
  }
  return lines
}

// Every position of a tail analysed as a command start, wrappers peeled, so `sh -c "rm -rf x"`
// behind a runner or in a container reads as `rm -rf x`. The tail came from a best-effort flag
// table or none (a container runtime), so judging every position fails closed.
export function tailViews(tail, unescape = false) {
  return viewsOf(tail, unescape, () => true)
}

// The analysis of `tail` from each position whose token passes `startsAt`; a view left with no
// program (`bun run` with nothing after it) has nothing to judge and is dropped.
function viewsOf(tail, unescape, startsAt) {
  return tail
    .map((token, i) => (startsAt(token) ? analyzeTokens(tail.slice(i), unescape).tokens : []))
    .filter(view => view.length > 0)
}

function analyzeSegment(segment, unescape) {
  return analyzeTokens(tokenize(segment, unescape), unescape)
}

// Peels assignments, wrappers, runners and `python -m` until the real program is first.
// - `tails` holds the raw tokens after each wrapper and after each runner's subcommand.
// - `scripts` holds each command string handed to a shell (see commandLines).
function analyzeTokens(words, unescape) {
  let tokens = words
  const tails = []
  const scripts = []
  // The flags of an `env` just peeled: with no program left it is a bare `env`, which prints the
  // environment, so the caller must still see it.
  let envFlags = null
  for (let depth = 0; depth <= MAX_WRAPPER_DEPTH; depth += 1) {
    while (tokens.length > 0 && /^[A-Za-z_]\w*=/.test(tokens[0])) tokens = tokens.slice(1)
    if (tokens.length === 0) {
      return { tokens: envFlags === null ? [] : ['env', ...envFlags], tails, scripts }
    }
    const program = programName(tokens[0])
    const inner = unwrap(program, tokens, tails)
    if (inner === null) return { tokens, tails, scripts }
    const { flags, rest } = stripWrapperFlags(program, inner, unescape, scripts)
    envFlags = program === 'env' ? flags : null
    tokens = rest
    if (tokens.length > 0 && /\s/.test(tokens[0])) {
      scripts.push(tokens[0])
      tokens = [...tokenize(tokens[0], unescape), ...tokens.slice(1)]
    }
  }
  // Still wrapped after the last peel: refuse what cannot be inspected.
  return block(
    `more than ${MAX_WRAPPER_DEPTH} nested wrappers or runners (sudo, env, uv run, …) in one ` +
      'command; the program behind them cannot be judged, blocking by default'
  )
}

// The tokens after `program` when it runs another one (a runner, `python -m`, a wrapper), or
// null when it is the real program. A runner's or a wrapper's raw tail is pushed to `tails`.
function unwrap(program, tokens, tails) {
  if (Object.hasOwn(RUNNERS, program)) {
    const stripped = stripRunner(RUNNERS[program], tokens)
    if (stripped === null) return null
    // A null `rest`: the subcommand sits behind a flag the table does not know. The tail is
    // recorded for the callers that judge every later token, and the tokens stay as written.
    tails.push(stripped.tail)
    return stripped.rest
  }
  // `python -m pytest` runs the module `pytest`; inline code and scripts stay as they are.
  if (PYTHON_PROGRAM.test(program)) return pythonModule(tokens.slice(1))
  if (!WRAPPERS.has(program)) return null
  tails.push(tokens.slice(1))
  return tokens.slice(1)
}

// Drops a wrapper's own flags and their values (`-lc`, `-NoProfile -Command`, `-u root`, `--`,
// cmd's `/c`) and timeout's duration. `flags` lists the flags without their values; a flag
// whose value is a command line (fish's -C) adds the value to `scripts`.
function stripWrapperFlags(program, inner, unescape, scripts) {
  const flags = []
  let i = 0
  while (i < inner.length && isWrapperFlag(program, inner[i])) {
    const flag = inner[i]
    flags.push(flag)
    i += 1
    if (flag === '--') break
    const glued = program === 'cmd' ? CMD_GLUED.exec(flag) : null
    if (glued !== null) return { flags, rest: [glued[1], ...inner.slice(i)] }
    const split = program === 'env' ? ENV_SPLIT.exec(flag) : null
    const init = program === 'fish' ? FISH_INIT.exec(flag) : null
    const valued = split ?? init
    if (valued !== null) {
      const attached = valued[1] !== ''
      const value = attached ? valued[1] : (inner[i] ?? '')
      if (!attached) i += 1
      if (init !== null) {
        scripts.push(value)
        continue
      }
      // env reads escapes (`\_` is a space) and `${VAR}` in the string, which the shell
      // tokenizer does not.
      if (/\\|\$\{/.test(value)) {
        block('env -S with a backslash escape or ${VAR} cannot be judged; blocking by default')
      }
      return { flags, rest: ['env', ...tokenize(value, unescape), ...inner.slice(i)] }
    }
    if (wrapperTakesValue(program, flag)) i += 1
  }
  if (program === 'timeout' && DURATION.test(inner[i] ?? '')) i += 1
  return { flags, rest: inner.slice(i) }
}

function isWrapperFlag(program, token) {
  if (token.startsWith('-')) return true
  // POSIX shells also take `+o name` and `+x`; cmd and powershell take `/c`, cmd `/e:on` too.
  if (WRAPPER_FLAGS[program] === SHELL_FLAGS) return /^\+[A-Za-z]+$/.test(token)
  if (program === 'cmd') return /^\/[a-z](:\w*)?$/i.test(token) || CMD_GLUED.test(token)
  return isPowerShell(program) && /^\/[a-z]+(:\S*)?$/i.test(token)
}

function wrapperTakesValue(program, flag) {
  if (isPowerShell(program)) return powershellTakesValue(flag)
  const valueFlags = WRAPPER_FLAGS[program] ?? NO_FLAGS
  // GNU getopt accepts any unambiguous prefix of a long option (`--sig KILL`).
  const abbreviates = name => name.startsWith('--') && name.startsWith(flag)
  if (/^--[^=]+$/.test(flag) && [...valueFlags].some(abbreviates)) return true
  return readFlag(flag, valueFlags).takesValue
}

function isPowerShell(program) {
  return program === 'powershell' || program === 'pwsh'
}

// A PowerShell parameter is named by any prefix (`-ex`), or by `-name:value` with its value
// attached. An encoded command cannot be inspected, so -EncodedCommand blocks.
function powershellTakesValue(flag) {
  const [name, ...attached] = flag.replace(/^(--?|\/)/, '').toLowerCase().split(':')
  const prefixOf = params => name.length >= 2 && params.some(param => param.startsWith(name))
  const encoded = name.startsWith('en') && prefixOf(POWERSHELL_ENCODED_PARAMS)
  if (encoded || ['e', 'ec', 'ea'].includes(name)) {
    block('powershell -EncodedCommand hides the command it runs; blocking by default')
  }
  if (attached.length > 0) return false
  if (POWERSHELL_VALUE_ALIASES.has(name)) return true
  return prefixOf(POWERSHELL_VALUE_PARAMS) && !prefixOf(POWERSHELL_REST_PARAMS)
}

// Package runners (`bun run pkg`, `uv run prog`, …) run the program named after their flags.
// - The tables list value flags, which consume the next token; otherwise
//   `uv run --directory backend rm` reads `backend` as the program.
// - Best effort, from uv 0.12.23 and bun 1.4 `--help` (plus uv's hidden --python-preference,
//   --preview-features, --python-fetch), `npm exec --help`, and the poetry, pdm, hatch CLI docs.
// - Left out on purpose: bun's -e/-p/--inspect* (optional values), npm's -c (a command string,
//   re-tokenised) and -p (--parseable). pipx, pnpm and yarn have no table.
const UV_GLOBAL =
  '--cache-dir --color --allow-insecure-host --directory --project --config-file ' +
  '--python-preference --preview-features --python-fetch'
const UV_COMMON =
  `${UV_GLOBAL} -w --with --with-editable --with-requirements --python-platform --index ` +
  '--default-index -i --index-url --extra-index-url -f --find-links --index-strategy ' +
  '--keyring-provider -P --upgrade-package --upgrade-group --resolution --prerelease ' +
  '--prerelease-package --fork-strategy --exclude-newer --exclude-newer-package ' +
  '--no-sources-package --reinstall-package --link-mode -C --config-setting ' +
  '--config-settings-package --no-build-isolation-package --no-build-package ' +
  '--no-binary-package --refresh-package -p --python --env-file'
const UV_RUN_FLAGS = flagSet(
  `${UV_COMMON} --extra --no-extra --group --no-group --only-group --no-editable-package --package`
)
const UV_TOOL_FLAGS = flagSet(
  `${UV_COMMON} --from -c --constraints -b --build-constraints --overrides --torch-backend`
)
const BUN_RUN_FLAGS = flagSet(
  '--elide-lines -F --filter --shell --watch-kill-signal -r --preload --require --import ' +
    '--cpu-prof-name --cpu-prof-dir --cpu-prof-interval --heap-prof-name --heap-prof-dir ' +
    '--heap-prof-interval --install --port --conditions --fetch-preconnect ' +
    '--max-http-header-size --dns-result-order --redirect-warnings --disable-warning --title ' +
    '--unhandled-rejections --console-depth --user-agent --cron-title --cron-period ' +
    '--main-fields --extension-order --tsconfig-override -d --define --drop --feature -l ' +
    '--loader --jsx-factory --jsx-fragment --jsx-import-source --jsx-runtime --env-file ' +
    '--cwd -c --config'
)
const BUNX_FLAGS = flagSet('-p --package')
const NPM_FLAGS = flagSet('--package -w --workspace --script-shell')

// A runner entry; an omitted flag table means no value flags.
// - `global` and `flags`: value flags before and after the subcommand words (`path`).
// - `envPrefix`: the program may carry a `name:` prefix (hatch).
// - `module`: -m/--module runs `python -m <module>`. `stdin`: what reads a script after `-`.
const sub = (path, flags = NO_FLAGS, options = {}) => ({ path, flags, ...options })
const RUNNERS = {
  bun: {
    global: BUN_RUN_FLAGS,
    subs: [sub(['x'], BUNX_FLAGS), sub(['run'], BUN_RUN_FLAGS, { stdin: 'bun' })]
  },
  bunx: { global: BUNX_FLAGS, subs: [sub([], BUNX_FLAGS)] },
  npm: {
    global: NPM_FLAGS,
    subs: [sub(['exec'], NPM_FLAGS), sub(['run'], NPM_FLAGS), sub(['x'], NPM_FLAGS)]
  },
  pnpm: { subs: [sub(['dlx']), sub(['exec']), sub(['run'])] },
  yarn: { subs: [sub(['dlx']), sub(['run'])] },
  uv: {
    global: flagSet(UV_GLOBAL),
    subs: [
      sub(['run'], UV_RUN_FLAGS, { module: true, stdin: 'python' }),
      sub(['tool', 'run'], UV_TOOL_FLAGS)
    ]
  },
  uvx: { global: UV_TOOL_FLAGS, subs: [sub([], UV_TOOL_FLAGS)] },
  poetry: { global: flagSet('-C --directory -P --project'), subs: [sub(['run'])] },
  pipx: { subs: [sub(['run'])] },
  pdm: {
    subs: [sub(['run'], flagSet('-p --project -k --skip --venv --env --env-file --working-dir'))]
  },
  hatch: {
    global: flagSet('-e --env -p --project --data-dir --cache-dir --config'),
    subs: [sub(['run'])],
    envPrefix: true
  }
}

// Splits a runner call into `rest` (program first, flags stripped) and `tail` (raw tokens after
// the subcommand); null for a non-runner call (`bun install`, `uv sync`). When an unknown flag
// shifted the subcommand, `rest` is null and only `tail` is reported.
function stripRunner(runner, tokens) {
  const subAt = at =>
    runner.subs.find(candidate =>
      candidate.path.every((word, offset) => tokens[at + offset]?.toLowerCase() === word)
    )
  let i = skipFlags(tokens, 1, runner.global ?? NO_FLAGS)
  const found = subAt(i)
  if (found === undefined) {
    for (let at = 1; at < tokens.length; at += 1) {
      const later = subAt(at)
      if (later !== undefined) return { rest: null, tail: tokens.slice(at + later.path.length) }
    }
    return null
  }
  i += found.path.length
  const tail = tokens.slice(i)
  const seen = new Set()
  const end = skipFlags(tokens, i, found.flags, seen)
  let rest = tokens.slice(end)
  const moduleValue = tokens.slice(i, end).find(token => token.startsWith('--module='))
  // uv's own Python channels: `-m/--module <mod>` runs `python -m <mod>` and a leading `-`
  // hands a script on stdin to the interpreter. Rewriting them lets the Python analysis judge
  // them, inline modules and stdin included.
  if (found.module && moduleValue !== undefined) {
    rest = ['python', '-m', moduleValue.slice('--module='.length), ...rest]
  } else if (found.module && (seen.has('-m') || seen.has('--module'))) {
    rest = ['python', '-m', ...rest]
  } else if (found.stdin !== undefined && rest[0] === '-') {
    rest = [found.stdin, ...rest]
  }
  return { rest: runner.envPrefix ? stripHatchSelectors(rest) : rest, tail }
}

// Index of the first token after the flags from `start`; `--` ends them. `seen`, when given,
// collects the flag names met.
function skipFlags(tokens, start, valueFlags, seen) {
  let i = start
  while (i < tokens.length && tokens[i].startsWith('-') && tokens[i] !== '-') {
    const flag = tokens[i]
    i += 1
    if (flag === '--') break
    const { names, takesValue } = readFlag(flag, valueFlags)
    for (const name of names) seen?.add(name)
    if (takesValue) i += 1
  }
  return i
}

// The flag names in one token and whether the next token is their value.
// - A flag in `valueFlags` takes the next token, unless written `--flag=value`.
// - A short cluster is read by letter: `-qp 3.14` gives 3.14 to -p, `-pq` gives it `q`.
function readFlag(flag, valueFlags) {
  if (flag.includes('=')) return { names: [flag.slice(0, flag.indexOf('='))], takesValue: false }
  if (valueFlags.has(flag)) return { names: [flag], takesValue: true }
  if (!/^[-+][A-Za-z]{2,}$/.test(flag)) return { names: [flag], takesValue: false }
  const sign = flag[0]
  const letters = [...flag.slice(1)]
  const first = letters.findIndex(letter => valueFlags.has(sign + letter))
  const read = letters.slice(0, first === -1 ? letters.length : first + 1)
  return { names: read.map(letter => sign + letter), takesValue: first === letters.length - 1 }
}

// `hatch run +py=3.10 -version=9000 test:pytest`: matrix selectors, then `env:program`.
function stripHatchSelectors(tokens) {
  let i = 0
  while (i < tokens.length && /^[+-]\w+=/.test(tokens[i])) i += 1
  const rest = tokens.slice(i)
  if (rest.length > 0) rest[0] = rest[0].replace(/^[\w.-]+:(?![\\/])/, '')
  return rest
}

// `python`, `python3`, `python314`, `python3.14t`, `py`, `pyw`, `pypy3`, `ipython`, … (a `.exe`
// suffix is gone by now).
const PYTHON_PROGRAM = /^(pyw?|pythonw?(\d+(\.\d+)?[a-z]*)?|pypy\d*(\.\d+)?|ipython\d*)$/
// Modules that run code handed to them as an argument or from stdin (`ipython` stands for
// IPython too: module names are compared in lower case).
const PYTHON_INLINE_MODULES = new Set([
  'timeit', 'cprofile', 'profile', 'trace', 'code', 'pdb', 'runpy', 'asyncio', 'ipython'
])
// The subset that is a REPL: with no argument it reads its program from stdin.
const PYTHON_REPL_MODULES = new Set(['code', 'pdb', 'asyncio', 'ipython'])
// Programs that run code handed to them inline or on stdin, and the language they read; the
// views of an unresolved tail look for these.
const SCRIPT_RUNTIMES = new Map([
  ['node', 'node'], ['bun', 'node'], ['deno', 'node'], ['tsx', 'node'], ['ts-node', 'node'],
  ['perl', 'perl'], ['ruby', 'ruby'], ['php', 'php']
])
// The flag that hands a runtime its code, which is attached to it or follows it:
// - node and its kin: -e, -p, -pe, --eval, --print (`-e'code'`, `--eval=code`).
// - perl and ruby: -e (perl's -E too), alone or ending a cluster such as -lne. Only switches
//   without an attached value may precede it, so `-MTest::More` names a module.
// - php: -r, and -B, -R, -E, which run code around each input line.
const INLINE_FLAG = {
  node: /^(?:--(?:eval|print)(?:=([\s\S]*))?|-(?:pe|ep)|-[ep]([\s\S]*))$/,
  perl: /^-[acfnpsStTuUvwWXl0-9]*?[eE]([\s\S]*)$/,
  ruby: /^-[acdhlnpsvwyUW0-9]*?e([\s\S]*)$/,
  php: /^-[rRBE]([\s\S]*)$/
}
// Flags that mean an interpreter is not reading a program from stdin: version and help, a code
// argument (handled elsewhere), node's test and run modes.
const NO_STDIN_FLAG =
  /^(-[vVhcep]|--(version|help|test.*|check|run.*|eval.*|print.*|inspect.*|v8-options|completion-bash))$/

export function isPythonProgram(program) {
  return PYTHON_PROGRAM.test(program)
}

// The language a program interprets: 'python', 'node' (node, bun, deno, tsx, ts-node), 'perl',
// 'ruby' or 'php'; null for any other program.
export function runtimeOf(program) {
  if (PYTHON_PROGRAM.test(program)) return 'python'
  return SCRIPT_RUNTIMES.get(program) ?? null
}

// The code an interpreter call runs from its command line (`''` when it is inline but the code
// is missing), or null when there is none. Everything after the flag counts, which errs towards
// judging more text.
export function inlineCode(program, args) {
  const runtime = runtimeOf(program)
  if (runtime === 'python') return pythonInlineCode(args)
  if (runtime === null) return null
  if (program === 'deno' && args[0] === 'eval') return args.slice(1).join(' ').trim()
  return scriptInlineCode(args, runtime)
}

// True when an interpreter reads its program from stdin (a `-`, a heredoc, a pipe, a REPL).
export function readsStdin(program, args) {
  const runtime = runtimeOf(program)
  if (runtime === 'python') return pythonReadsStdin(args)
  return runtime !== null && scriptReadsStdin(args)
}

// Redirections are not arguments: `python - <<EOF`, `python < in.py`, `python 2>err`.
function withoutRedirections(args) {
  const out = []
  for (let i = 0; i < args.length; i += 1) {
    const match = /^(?:\d+|&)?(?:<<<|<<|<|>>|>)(.*)$/.exec(args[i])
    if (match === null) out.push(args[i])
    else if (match[1] === '') i += 1
  }
  return out
}

// Reads how the interpreter was invoked, the way Python parses its own command line:
//   { kind: 'inline', code }         -c <code> (also attached, or in a cluster such as -Ic)
//   { kind: 'module', module, rest } -m <module>
//   { kind: 'stdin' }                `-`, or nothing to run at all (stdin or a REPL)
//   { kind: 'other' }                a script path first, or --version, -h, …
// Only options before the script count, so `python run.py -c conf` is a script run.
function parsePython(rawArgs) {
  const args = withoutRedirections(rawArgs)
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i]
    if (arg === '-') return { kind: 'stdin' }
    if (arg === '--') continue
    if (/^--(version|help)$/.test(arg)) return { kind: 'other' }
    if (arg.startsWith('--')) {
      if (arg === '--check-hash-based-pycs') i += 1
      continue
    }
    if (!arg.startsWith('-')) return { kind: 'other' }
    for (let k = 1; k < arg.length; k += 1) {
      const attached = arg.slice(k + 1)
      const value = attached !== '' ? attached : (args[i + 1] ?? '')
      if (arg[k] === 'c') return { kind: 'inline', code: value }
      if (arg[k] === 'm') {
        return { kind: 'module', module: value, rest: args.slice(attached !== '' ? i + 1 : i + 2) }
      }
      if (arg[k] === 'W' || arg[k] === 'X') {
        if (attached === '') i += 1
        break
      }
      if (/^V+$|^h$/.test(arg.slice(k))) return { kind: 'other' }
    }
  }
  return { kind: 'stdin' }
}

function runsModule(parsed, modules) {
  return parsed.kind === 'module' && modules.has(parsed.module.toLowerCase())
}

// The module tokens of `python [flags] -m <module> …` (the module name first), or null when
// the invocation runs inline code, a script, or a module that executes its argument.
function pythonModule(args) {
  const parsed = parsePython(args)
  if (parsed.kind !== 'module' || parsed.module === '') return null
  return runsModule(parsed, PYTHON_INLINE_MODULES) ? null : [parsed.module, ...parsed.rest]
}

// The code an interpreter call executes from its command line (`''` when it is inline but
// the code is missing), or null when there is none: `-c <code>`, or the arguments of a module
// such as `timeit` that runs them as code. Scripts and plain modules have no inline code.
export function pythonInlineCode(args) {
  const parsed = parsePython(args)
  if (parsed.kind === 'inline') return parsed.code
  return runsModule(parsed, PYTHON_INLINE_MODULES) ? parsed.rest.join(' ') : null
}

// True when the interpreter reads its program from stdin (`python -`, `python <<EOF`,
// `… | python`, a REPL module such as `python -m asyncio`), so the code is in a heredoc or a
// pipe and not in the arguments.
export function pythonReadsStdin(args) {
  const parsed = parsePython(args)
  const repl = runsModule(parsed, PYTHON_REPL_MODULES) && parsed.rest.length === 0
  return parsed.kind === 'stdin' || repl
}

// The same for node, bun, deno and the other script runtimes: a `-` argument, or no program to
// run at all (a bare interpreter in a pipe, or flags only), means the code is on stdin.
export function scriptReadsStdin(rawArgs) {
  const args = withoutRedirections(rawArgs)
  if (args.includes('-')) return true
  return args.every(arg => arg.startsWith('-') && !NO_STDIN_FLAG.test(arg))
}

// The code after the runtime's inline flag (see INLINE_FLAG), code over several lines included,
// or null when the call is not inline.
export function scriptInlineCode(args, runtime = 'node') {
  const inline = INLINE_FLAG[runtime]
  for (let i = 0; i < args.length; i += 1) {
    const match = inline.exec(args[i])
    if (match !== null) return [match[1] ?? match[2] ?? '', ...args.slice(i + 1)].join(' ').trim()
  }
  return null
}
