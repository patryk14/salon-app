# salon-api — Charm Skin backend

FastAPI + SQLAlchemy 2 + psycopg 3, dependencies managed by [uv](https://docs.astral.sh/uv/).

## Running locally

Simplest: `docker compose up` in the repo root (database, MinIO, Mailpit and the API together).

Without Docker (requires a running Postgres):

```sh
uv sync
export DATABASE_URL=postgresql+psycopg://salon:salon@localhost:5432/salon
export S3_BUCKET=salon-photos SMTP_HOST=localhost SMTP_PORT=1025
export CORS_ORIGINS=http://localhost:4321   # Astro dev server
uv run uvicorn --factory app.main:create_app --reload
```

The application is created through a **factory** (`create_app()`), not a module-level `app`:
configuration is validated at process start (fail-fast), while `import app.main` itself
needs no environment variables (tests, alembic, OpenAPI export in CI).

## Tests and lint

```sh
uv run pytest
uv run ruff check
uv run ruff format --check
```

Tests do not connect to the database (`tests/conftest.py` sets env only so that
`Settings` validation passes).

## Configuration

Everything comes from environment variables (`app/config.py`). Secrets and
environment-dependent values (`DATABASE_URL`, `CORS_ORIGINS`) have no defaults — a missing
variable stops the application from starting. AWS credentials are resolved by boto3 itself
(locally `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` for MinIO, in AWS an IAM role); the
`boto3` package joins the dependencies together with the first photo endpoint (presigned URL).

| Variable          | Required | Description                                             |
|-------------------|----------|---------------------------------------------------------|
| `DATABASE_URL`    | yes      | `postgresql+psycopg://user:pass@host:5432/db`           |
| `S3_BUCKET`       | yes      | photo bucket                                            |
| `SMTP_HOST`       | yes      | `mailpit` locally, the SES endpoint in AWS              |
| `CORS_ORIGINS`    | yes      | comma-separated frontend origins; `http://localhost:4321` locally, the site domain in AWS |
| `S3_ENDPOINT_URL` | no       | set locally only (MinIO); empty in AWS                  |
| `AWS_REGION`      | no       | default `eu-central-1`                                  |
| `SMTP_PORT`       | no       | default `587` (`1025` locally)                          |
| `APP_ENV`         | no       | `local` / `lab` / `prod`, default `local`; `prod` disables `/docs` |

## Endpoints

- `GET /healthz` — liveness, no database → `{"status":"ok","service":"salon-api"}`
- `GET /readyz` — readiness, `SELECT 1` on the database → 200 or 503
- `GET /docs`, `GET /openapi.json` — Swagger UI / OpenAPI schema, **outside prod only**
  (`APP_ENV=prod` → 404; a public schema is a free map of the API)

## Image

```sh
make build                          # from the repo root — same tag as in docker-compose.yml
docker build -t salon-api:local .   # the same, from here
```

Multi-stage Dockerfile: builder `uv:0.12.7-python3.13-trixie-slim` (uv version pinned to
the one in `mise.toml`), runtime `python:3.13-slim-trixie` without `pip`, non-root user,
`HEALTHCHECK` on `/healthz`. Runs on arm64 and amd64.

The frontend is static and calls the API from the browser (different origin), so the app
has `CORSMiddleware` with the origins from `CORS_ORIGINS` — in AWS that is the site domain.
