---
paths: ["scripts/**", ".claude/hooks/**"]
---

# Code style

Applies to the harness's own JavaScript: `scripts/` and `.claude/hooks/`. A generated
package follows its own `AGENTS.md` and its `format` command.

- No trailing semicolons. When a semicolon is required for syntax safety, put it at the
  start of the line:

  ```js
  const value = getValue()
  ;(() => init())()
  ```

- The harness files are written by hand in the Prettier style: `semi: false`,
  `singleQuote: true`, `printWidth: 100`. The harness has no formatter script.
- Plain ESM JavaScript on Node built-ins, no dependencies and no build step. Named exports.
  Small files with one responsibility.
- Comments say why, not what, in two or three sentences at most; use bullets when they read
  better. No commented-out code.
