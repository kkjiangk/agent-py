# API contracts

Shared TypeScript HTTP, error, OpenAPI, SSE, retrieval, and ownership contracts for the frontend and backend. Public exports live in `src/index.ts`; updates must preserve strict TypeScript compatibility and synchronize clients and backend behavior.

From the repository root:

```bash
npm run contracts:typecheck
npm --workspace packages/api-contracts test
```

Kafka remediation commands include a stable `commandId`. Their transport is at least once; an executor must deduplicate before applying side effects. See [Architecture](../../docs/architecture.md).
