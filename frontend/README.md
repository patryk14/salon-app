# Charm Skin — frontend

Static salon website (Astro, `strict` tsconfig). No SSR, no adapter: the build output is
plain files in `dist/`, served from S3 through CloudFront.

## Layout

```text
frontend/
├── public/            # files copied 1:1 into dist/ (favicon etc.)
├── src/
│   └── pages/
│       └── index.astro  # home page + "Status API" section
├── astro.config.mjs   # output: 'static' + environment variable schema (astro:env)
└── Dockerfile.dev     # docker compose only (dev server with hot reload)
```

## Environment variables

| Variable         | Default                 | Description                                       |
| ---------------- | ----------------------- | ------------------------------------------------- |
| `PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend (no trailing `/`) |

Schema, type and default live in **one place**: `astro.config.mjs` (`env.schema`, the
`astro:env` idiom). In code: `import { PUBLIC_API_URL } from 'astro:env/client'`.
Variables with `context: 'client'` are **compiled into the bundle** during `npm run build` —
they cannot be changed at runtime. A different backend means a new build. For the same
reason secrets must never be placed here.

## Development

### Locally (without Docker)

```sh
npm ci
npm run dev        # http://localhost:4321
```

### In docker compose (with the whole stack)

From the `salon-app/` directory:

```sh
docker compose up web
```

The `web` service builds `Dockerfile.dev` (node:24-alpine, user `node`,
`astro dev --host 0.0.0.0`) and exposes port `4321` on loopback. `PUBLIC_API_URL` is set in
compose to `http://localhost:8000` — the fetch runs **in the browser**, so the address must
be reachable from the host, not from the compose network (hence not `http://api:8000`).

Compose mounts `./frontend:/app` **and** a named volume `web_node_modules` on
`/app/node_modules` (otherwise an empty `node_modules` from the host would shadow the one
from the image). The volume is filled from the image only once, so **after changing `package.json`**:

```sh
docker compose down web && docker volume rm salon_web_node_modules && docker compose up -d --build web
```

(Not `down -v web`: `-v` deletes every unused project volume, including DB/MinIO data,
whenever the stack happens to be down.)

On macOS (colima/virtiofs, Docker Desktop) the bind mount delivers no inotify events, so
compose sets `CHOKIDAR_USEPOLLING=true` — without it HMR never sees changes.
The dev server starts with `--ignore-lock`, because the `.astro/dev.json` lock (holding a
PID) would land on the bind mount and survive `docker compose down` — the next start would
fail with "Another astro dev server is already running".

## Production build (no container)

```sh
PUBLIC_API_URL=https://api.charmskin.pl npm run build
npm run preview    # optional: preview dist/ locally
```

Output lands in `dist/`. Deployment is a plain `aws s3 sync dist/ s3://<bucket>` plus a
CloudFront invalidation — eventually done by CI (GitHub Actions via OIDC, arriving in
Stage 1), not by a container. `Dockerfile.dev` is not used in production at all.

## The "Status API" section

The home page queries `${PUBLIC_API_URL}/healthz` client-side and shows the result. It
exists only to verify that the frontend → backend bridge works (including CORS). To be
removed/moved once real content arrives.
