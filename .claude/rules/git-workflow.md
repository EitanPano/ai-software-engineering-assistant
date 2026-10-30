# Git workflow

Applies to every session and every agent.

- Never commit, merge, push or tag without explicit approval from the user.
- Implementation work happens on a dedicated branch, never on `main`. One task or
  workstream per branch: `feat/<topic>`, `fix/<topic>`, `chore/<topic>`, `docs/<topic>`,
  lowercase, singular domain terms.
- Conventional Commits: `type(scope): summary`, imperative, one intent per commit.
  Types: `feat`, `fix`, `refactor`, `test`, `chore`, `docs`.
- Agents never rewrite history, force-push, hard-reset or delete branches; a human does.
- Release tagging and version numbers follow the `cutting-a-release` skill.
