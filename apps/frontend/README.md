# Frontend

Vue 3, TypeScript, Pinia, Vue Router, Vite, Vitest, and Playwright. The current user interface is Chinese and supports desktop and narrow-screen layouts.

Run from the repository root:

```bash
npm ci
npm run frontend:dev
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
npm exec --workspace apps/frontend playwright install chromium
npm run frontend:e2e
```

Typed API/SSE clients use `packages/api-contracts`. Authentication and global operation feedback use shared stores and components. Pages cover chat, knowledge documents, diagnosis, and MCP connections.

The Node-side public-config plugin exports only `frontend.apiBaseUrl`; private JSON is not imported into browser modules. Template fallback supports clean builds. E2E mode uses an isolated local proxy and test backend, with real auth/SQLite/jobs/SSE and explicit test-only external adapters.

See [Configuration](../../docs/configuration.md) and [Testing](../../docs/testing.md).
