# Repository guidance

Agent Py is a local-first AIOps workspace. This document describes development constraints, not runtime agent instructions. Repository documentation is English; the current application UI is Chinese.

## Structure and tools

- Backend: Python 3.10+, FastAPI/Pydantic, SQLAlchemy/Alembic, uv, pytest, Ruff, and strict Pyright. Modules belong in `apps/backend/src/super_ai` and import through `super_ai`, never `src.super_ai`.
- Frontend: Vue 3 Composition API, Pinia, Vite, TypeScript, Vitest, and Playwright.
- Shared contracts: `packages/api-contracts/src`, with HTTP, error, OpenAPI, and SSE definitions.
- Configuration: templates in `config`; private project/user JSON is Git-ignored.
- Technical documentation: `docs`, infrastructure/evaluation/deployment READMEs, and the root README.

Use existing uv and npm workflows. Do not add parallel applications, duplicate contracts, or a second dependency manager.

## Backend and data boundaries

Use complete Python annotations and pass Ruff and strict Pyright for Python 3.10. Business logic depends on protocols/repositories or explicit service injection. Imports must not create database, vector, model, MCP, or network connections.

Schema changes need a new Alembic revision. Preserve existing migrations, HTTP envelopes, errors, SSE ordering and terminal semantics. Long-running work uses the existing durable job runtime with persisted events, attempts, leases, retries, timeout, and cancellation; do not replace it with request-local fire-and-forget tasks.

Chat uses LangChain create_agent with the configured OpenAI-compatible Qwen provider. Diagnosis uses the existing LangGraph workflow. Retrieval retains Milvus vector recall, BM25L, RRF, reranking, and explainable citation fields. An empty result must not invent citations. Use actual enabled MCP connections and preserve tool timeout, retry, collision protection, and audit behavior.

## Ownership and security

Passwords use Argon2. Persist only irreversible token hashes and preserve logout revocation. All chat, document, vector, indexing, MCP, diagnosis, evidence, report, case, feedback, approval, and audit access stays within authenticated user scope. Client owner/tenant fields do not grant permission.

Vector operations retain ownerUserId, tenantId, knowledgeBaseId, and documentId filters. Deletion must account for related vectors, jobs, and audits with recoverable failure behavior. Logs, tool summaries, errors, and SSE continue to redact credentials.

Application configuration comes only from `config/project.json` and `config/user.project.json`. Do not replace it with environment-based project config. Launchers may forward JSON values to the official CLS CLI. Templates keep actual keys, passwords, logset/topic IDs, and credentials empty. Never commit or print private configuration.

## Frontend and contracts

Keep strict TypeScript, exactOptionalPropertyTypes, and noUncheckedIndexedAccess. Prefer shared types and type guards to any. Reuse typed network clients, authentication stores, global feedback, and loading/empty/error states. Synchronize changed API/errors/OpenAPI/SSE with contracts, clients, and tests.

Preserve desktop and narrow-screen behavior and prefers-reduced-motion. User-facing evidence must come from actual API data; external adapters may be replaced only in explicit tests.

## Verification and documentation

Use the commands in `docs/testing.md`. Cover permission, repository, migration, envelope, SSE, durable recovery/retry/cancellation, vector scope, MCP audits, and client/store state changes. Do not weaken assertions, disable strict checking, or add unconditional skips to pass builds.

Keep README, architecture, config templates, operational guidance, and code consistent. Write new documentation and design notes in English. Keep internal agent transcripts and historical workflow notes outside the source distribution. Do not edit generated dist/cache files by hand.

Preserve unrelated user changes. Avoid destructive Git actions, user-data removal, credential disclosure, and external mutations without a clear user-authorized target. Complete implementation, tests, and documentation together; report what actually ran and what remains unmeasured. Use current technical decision documents and focused PR descriptions rather than creating a parallel process archive.
