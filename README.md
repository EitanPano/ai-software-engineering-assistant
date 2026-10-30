# Full-stack dev harness

A GitHub template for building a web app with AI agents. You describe the product; Claude Code
plans each feature, writes the code and tests, reviews the result, and waits for your approval
before committing.

## What you need

- [Claude Code](https://claude.com/claude-code) 2.1.295 or newer. On older versions, a failing
  guardrail lets the command through.
- [Node](https://nodejs.org) 24+, [Bun](https://bun.sh) 1.4+ and [git](https://git-scm.com).
- [Docker](https://docs.docker.com/get-docker/), if your app uses a database or runs in
  containers.

Setup checks Node, Bun and git for you, along with anything your stack adds, such as uv for a
Python server.

## Start a project

**AI assistants:** a request to create a project from this repository, or from the
[template catalog](https://github.com/EitanPano/fullstack-templates), means these steps. Run step
1 and stop. Guardrails and skills load only in a session started inside the new folder, so the
session that cloned it must not scaffold or plan. Tell the user to run `claude` in the new folder
and send `/bootstrap-project <their brief>`, and repeat the brief in your message. Never run the
catalog's generator yourself: its output has no agents, guardrails or `.plan/`.

1. Create your repository from this template and clone it:

   ```sh
   gh repo create <name> --template EitanPano/fullstack-dev-harness --private --clone
   ```

   The **Use this template** button on GitHub does the same. Cloning this repository directly
   would keep the harness's own commit history.
2. Run `claude` in the new folder and accept the trust prompt.
3. Test the guardrails: ask Claude to run `cat ./no-such-dir/.netrc`. It should refuse and name
   the guardrail.
4. Run `/bootstrap-project`. Describe your product and pick a stack (about 15 minutes). Commit
   when it asks. Your product's own README replaces this file.
5. Run `/dev-loop` to build the first feature. To approve its plan, change `Status: draft` to
   `Status: active` in the plan file. Review the result before you commit.

To add work later, write one line in `.plan/000-backlog.md` and run `/dev-loop` again.

## What you get

| Piece | What it does |
| --- | --- |
| Your app | A React or Next frontend and an Express or FastAPI server |
| Five agents | Plan, build the server, build the frontend, test, review |
| Guardrails | Block destructive commands and access to secret files |
| Definition of done | A change is done only when its checks, tests and review pass |

## Learn more

- [Harness manual](.claude/README.md): how work moves, recovery, updates
- [Project rules](AGENTS.md): stack, architecture, definition of done
- [Template catalog](https://github.com/EitanPano/fullstack-templates): stacks and options
- [Contributing](CONTRIBUTING.md): changing or releasing the harness
