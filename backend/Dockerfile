# syntax=docker/dockerfile:1
# Backend image — the same one runs locally (docker compose) and in AWS (ECR → Lambda).
# Multi-stage: uv installs dependencies in the builder; the runtime gets only the
# finished .venv plus the code. Base images are multi-arch (arm64/amd64) — nothing
# here is tied to an architecture.
#
# The uv version is pinned to the one in mise.toml (uv.lock must be generated and read
# by the same version), and builder and runtime share one distribution (Debian trixie).
# Digests (`@sha256:…`) arrive together with Renovate in CI — a pinned digest without
# a bot is just a frozen, unpatched base.

FROM ghcr.io/astral-sh/uv:0.12.7-python3.13-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies first (own layer — cached until the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

COPY app ./app


FROM python:3.13-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# The runtime installs nothing — .venv comes from the builder. pip from the base image
# is dead weight and the only source of CVEs we cannot patch ourselves (vendored
# msgpack/setuptools).
RUN python -m pip uninstall -y pip \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --from=builder --chown=app:app /app/app ./app

# AWS Lambda Web Adapter: a single static binary that Lambda discovers as an
# extension. Inside Lambda it translates invoke events into plain HTTP calls to
# uvicorn (port from AWS_LWA_PORT); anywhere else (compose, CI, EKS) the file just
# sits unused — it only activates when AWS_LAMBDA_RUNTIME_API is present. This is
# what lets ONE image serve both docker-run and Lambda without code changes.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

USER app
EXPOSE 8000

# No curl in the image — probe via stdlib. App Runner has its own health check (same path).
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# --factory: the app is created when the process starts (env validation = fail-fast),
# while importing the module needs no environment at all (tests, tooling, alembic).
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
