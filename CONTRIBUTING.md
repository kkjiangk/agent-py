# Contributing

## Development workflow

Read the [Architecture](docs/architecture.md) and [Engineering decisions](docs/engineering-quality.md), then configure local JSON as described in [Getting started](docs/getting-started.md). Use uv for the backend and npm workspaces for the web packages.

Keep changes focused. Preserve user ownership filters, HTTP envelopes, SSE terminal semantics, explicit background-job recovery, and audit redaction. Use repository protocols and injected providers for domain logic. New schema changes need a new Alembic revision; do not rewrite released migrations.

HTTP, error, OpenAPI, or SSE changes must update shared contracts and clients together. Add regression coverage for permission, persistence, retries, cancellation, migration, and protocol changes. Test adapters belong in tests rather than production user flows.

## Validation

Run the relevant target tests and the checks in [Testing](docs/testing.md). Documentation changes must pass the documentation build and local-link validation. Update configuration templates and instructions whenever fields, commands, or runtime behavior change.

Describe the concrete behavior, validation, and remaining limitations in a pull request. Conventional Commit prefixes such as `feat:`, `fix:`, `test:`, and `docs:` are encouraged. UI changes should include desktop evidence and narrow-screen verification.

## Repository hygiene

Keep documentation in English. Keep credentials, private local JSON, databases, generated frontend/docs assets, dependency directories, browser traces, and raw evaluation runs out of Git. Maintain architecture decisions as current technical documentation rather than publishing chat transcripts or agent prompt histories.

Use an isolated test account for actual model/MCP evaluation and keep raw traces local. External uploads, deployment, and remediation execution must have a clear operator-selected target.
