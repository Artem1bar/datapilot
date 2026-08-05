# DataPilot Frontend

React + TypeScript + Vite frontend for DataPilot — an AI-powered data cleaning tool.

## Dev setup

```bash
# From repo root
pnpm install
pnpm dev:web       # starts at http://localhost:5173
```

Or from this directory:

```bash
pnpm install
pnpm dev
```

## Environment variables

Copy `.env.example` at the repo root to `.env` and set:

| Variable | Description |
|----------|-------------|
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk publishable key (build-time; use `DEV_AUTH_BYPASS=true` locally to skip) |
| `VITE_API_URL` | Production API base URL (leave blank for local dev — the Vite proxy handles it) |

## Tests

```bash
pnpm test          # Vitest unit tests (128 tests)
pnpm test:e2e      # Playwright E2E (3 specs, requires API + DB running)
```

## Build

```bash
pnpm build         # outputs to dist/
pnpm preview       # preview the production build locally
```

See the [root README](../../README.md) for full project context, deployment instructions, and backend setup.
