# Both stages use the same python image: the venv's `python` is a symlink into the base image.
# Every image is pinned by digest, with its tag beside it (.doc/conventions.md, CI).
FROM python:3.14-slim@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /uvx /bin/
# The image installs Python packages only: uv never downloads an interpreter, and compiles
# bytecode once, here, so the non-root user needs to write nothing at runtime.
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
# Dependencies first: this layer is cached until pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14-slim@sha256:930e1abba7c4e8f96ed93e8012c35d174d7732752731bbd5e8e757d7ec6f3966
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# The built SPA from the frontend's `dist` target, served when STATIC_DIR names it.
COPY --from=spa --chown=app:app /dist ./public
ENV STATIC_DIR=/app/public
ENV PATH="/app/.venv/bin:$PATH" APP_ENV=production PORT=8000 PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
CMD ["python", "-m", "app.main"]
