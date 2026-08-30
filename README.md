# salon-app — Charm Skin

Application for the **Charm Skin** beauty salon: client profiles (visits, progress photos),
an admin panel replacing Excel spreadsheets, and a product catalogue with in-salon pickup.

This repo holds the **application code** (backend + frontend + container images). CI
(GitHub Actions → AWS via OIDC, no long-lived keys) arrives in Stage 1. AWS infrastructure
lives in `salon-infra` (Terraform), ArgoCD manifests in `salon-gitops`.

The project doubles as a training ground for GitOps, HA and AWS — which is why everything
that can be is reproducible from Git, and the local environment mirrors production as
faithfully as is reasonable (see ["The same image locally and in AWS"](#the-same-image-locally-and-in-aws)).

## Local architecture

`docker compose` brings up five services plus one one-shot container. Locally we emulate
**standard protocols only** — Postgres, S3 API, SMTP. Nothing AWS-specific (IAM, Cognito,
Route53) is emulated; **no LocalStack**.

```
                            browser (you)
        ┌──────────────┬──────────────┬──────────────┬──────────────┐
        │ :4321        │ :8000        │ :9001        │ :8025        │
        ▼              ▼              ▼              ▼
  ┌───────────┐  ┌───────────┐  ┌────────────┐  ┌────────────┐
  │   web     │  │   api     │  │   minio    │  │  mailpit   │
  │ Astro dev │  │ FastAPI   │─▶│ S3 API     │  │ UI   :8025 │
  │ :4321     │  │ uvicorn   │  │ API  :9000 │  │ SMTP :1025 │
  └───────────┘  │ :8000     │  │ UI   :9001 │  └────────────┘
                 └─────┬─────┘  └────────────┘        ▲
                       │  │           ▲               │
                       │  └───────────┼──── SMTP ─────┘
                       ▼              │
                 ┌───────────┐  ┌────────────┐
                 │    db     │  │ minio-init │  one-shot: creates the
                 │ Postgres  │  │ (minio/mc) │  `salon-photos` bucket and exits
                 │ 17 :5432  │  └────────────┘
                 └───────────┘
```

The browser talks to `api` directly (`PUBLIC_API_URL=http://localhost:8000`); `web` only
serves the frontend. Start order is enforced by healthchecks
(`depends_on: condition: service_healthy`): `api` starts only once the database answers
over TCP, the bucket exists and Mailpit is alive; `web` — once `api` answers on `/healthz`.

All ports are published **on 127.0.0.1 only**. A laptop ends up on untrusted networks, and
behind these ports sit Postgres, the MinIO root account, every e-mail and Swagger — on
`0.0.0.0` (the compose default) anyone on the same Wi-Fi would see them.

| Locally | In AWS | Protocol |
|---|---|---|
| `db` — postgres:17-alpine | RDS Postgres | PostgreSQL |
| `minio` — MinIO | S3 (private bucket, presigned URLs) | S3 API |
| `mailpit` — Mailpit | SES | SMTP |
| `api` — the same image | App Runner / Lambda — **the same image** | HTTP |
| `web` — Astro dev server | S3 + CloudFront (static build) | HTTP |

Third-party images (MinIO, mc, Mailpit) are pinned by tag **and digest** — two people
cloning the repo a month apart get the same thing. MinIO is a conscious exception: upstream
no longer publishes community images (the `latest` tag has been frozen since 2025-09), so
the pin merely makes the actual state explicit. Refreshing digests is left to a bot
(Renovate) together with CI.

## Requirements

- **Docker with Compose v2+.** On macOS via colima (as here, arm64) — note that colima
  provides only the VM with the daemon; the `docker` client, the `compose` plugin and
  `buildx` must be added and the CLI told where they are (brew caveat):

  ```sh
  brew install colima docker docker-compose docker-buildx
  mkdir -p ~/.docker && cat > ~/.docker/config.json <<'EOF'
  { "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"] }
  EOF
  colima start              # or: colima start --arch aarch64 --vm-type vz --mount-type virtiofs
  docker compose version    # should print v2+ (here: 5.x)
  ```

  Docker Desktop works the same without these steps. On Linux: the `docker-compose-plugin` package.
- **For tests, lint and the frontend build outside containers:** `python 3.13`, `uv 0.12.7`,
  `node 24` — versions are held in [`mise.toml`](mise.toml) at the repo root:
  `mise install` (once) and you are set. The uv version matches `backend/Dockerfile`,
  so `uv.lock` is generated and read by the same version.

## Running step by step

```bash
# 1. Local configuration — the values in .env.example are explicitly non-secret.
#    (Compose carries the same values as defaults, so it starts without .env too;
#    .env is for overrides — e.g. a different port or bucket.)
cp .env.example .env

# 2. Build images and start everything; --wait blocks until healthchecks pass
docker compose up -d --build --wait

# 3. Check it is alive
curl http://localhost:8000/healthz     # {"status":"ok","service":"salon-api"} — no DB access (probe)
curl http://localhost:8000/readyz      # 200 when SELECT 1 on the DB succeeds, 503 otherwise

# 4. Live logs
docker compose logs -f api

# 5. Done for the day (data in volumes is kept; `-v` deletes it)
docker compose down
```

The same via shortcuts: `make up`, `make logs`, `make down`. `make` alone lists all targets.

Backend code is bind-mounted into the container (`./backend/app` → `/app/app`) and compose
overrides the command with `uvicorn --reload` — a change to a `.py` file reloads the API
without a restart. The frontend likewise: `./frontend` → `/app`, Astro reloads the browser.
On macOS the bind mount (colima/virtiofs, Docker Desktop) delivers no inotify events into
the container, which is why compose sets `WATCHFILES_FORCE_POLLING=true` (uvicorn) and
`CHOKIDAR_USEPOLLING=true` (Vite) — without them reload never notices changes.

A dependency change requires an image rebuild:

- backend (`pyproject.toml`, `uv.lock`): `docker compose up -d --build api`
  (or `docker compose up --watch`, which rebuilds on its own);
- frontend (`package.json`):
  `docker compose down web && docker volume rm salon_web_node_modules && docker compose up -d --build web`
  — `node_modules` live in a named volume filled from the image only once; without removing
  the volume the new container would get the old `node_modules`. Note: **not** `down -v web` —
  `-v` with a service name still deletes every project volume not currently in use
  (i.e. the DB/MinIO data whenever the stack is down).

## Addresses

| What | URL | Notes |
|---|---|---|
| API | http://localhost:8000 | `/healthz` (liveness), `/readyz` (readiness, checks the DB) |
| API docs (Swagger) | http://localhost:8000/docs | generated by FastAPI; **outside prod only** (`APP_ENV=prod` → 404) |
| Frontend | http://localhost:4321 | Astro dev server, hot reload |
| MinIO console | http://localhost:9001 | login `minio` / `minio12345`, bucket `salon-photos` |
| Mailpit | http://localhost:8025 | every e-mail sent by the API lands here |
| Postgres | `localhost:5432` | `salon` / `salon`, database `salon` (e.g. `psql -h localhost -U salon salon`) |

## Tests and lint

```bash
make test    # backend: uv run --directory backend pytest
make lint    # backend: ruff check + ruff format --check
cd frontend && npm run build   # frontend: static build (the only verification for now)
```

Tests run **outside the container** (via `uv`), because the production image deliberately
contains neither pytest nor any other dev tooling. Tests do not connect to the database.

## The same image locally and in AWS

AWS receives **exactly the `api` image** you build locally from `backend/Dockerfile`
(`make build` builds it the way CI will). There is no separate "Dockerfile.prod" and no
`if APP_ENV == "local"` in the code. Differences between environments live in two places:

1. **Environment variables** — same names, different values. Locally `DATABASE_URL`
   points at the `db` container, in AWS at RDS; `S3_ENDPOINT_URL` is MinIO locally and
   empty in AWS (boto3 goes to real S3). Full list: `.env.example`.
   The `api` container receives an **explicit list** of variables (the `environment`
   section in compose), not the whole `.env` — the MinIO root login and the Postgres
   password have no business being in api.
2. **IAM** — locally `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are the MinIO login;
   in AWS these variables do not exist at all, because the container gets its permissions
   from a role.

The only things compose overrides relative to the image are `command` (`--reload`), the
code bind mount and the `WATCHFILES_FORCE_POLLING` variable — all serving the dev loop only.
Even the `api` healthcheck in compose has no probe of its own: it inherits `HEALTHCHECK`
from the image and only changes the interval.

Why: if the image works locally but not in AWS, the problem is configuration or
permissions — and that is exactly what we want to learn, instead of hunting for code differences.

## Repo layout

```
salon-app/
├── backend/            # FastAPI + Dockerfile (production image), tests, pyproject.toml
│   └── app/            # application code — bind-mounted into the container in compose
├── frontend/           # Astro; Dockerfile.dev only for the local dev server
├── docker-compose.yml  # local environment: api, db, minio, minio-init, mailpit, web
├── .env.example        # every environment variable with local values
├── mise.toml           # python / uv / node versions (mise install)
├── Makefile            # up / down / logs / test / lint / build / clean
├── .editorconfig
├── .gitignore          # the only one in the repo — patterns apply at every level
├── LICENSE             # MIT
└── README.md
```

Related repositories (separate directories next to this one):

- `salon-infra/` — Terraform: bootstrap (state, budget), `envs/dev` (pgajewsk.pl), `envs/lab` (EKS), `envs/prod` (later)
- `salon-gitops/` — ArgoCD app-of-apps: `platform/` + `apps/`

## Rules

- **Zero secrets in the repo.** The values in `.env.example` are logins to containers on a
  laptop. Real secrets live in SSM Parameter Store / Secrets Manager; `.env` is gitignored.
  Once real variables arrive (Cognito, SES), `gitleaks` joins CI.
- **Zero personal data in the repo** — including test fixtures and database dumps.
  Client photos are personal data (GDPR): private bucket only, encryption, EU region.
- Code, identifiers, comments and documentation in English. User-facing copy on the site
  is Polish (the salon's clients).

## License

MIT — see [LICENSE](LICENSE).
