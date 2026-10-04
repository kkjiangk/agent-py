# Engineering decisions

## Recoverable delivery

The Kafka consumer disables automatic commits. Processing and commit must succeed for the current record before another record is polled. Three default attempts use bounded backoff; exhaustion exits with the offset uncommitted. Redis distinguishes live leases from completed work and checks ownership before completion or release.

An approval transition and its deterministic dispatch job share one SQLite transaction. Atomic dispatch claims and token-checked updates prevent concurrent senders from independently completing the same claim. The existing durable runtime handles retries and restart recovery, instead of a second task system.

A broker acknowledgement and a database write cannot be committed atomically here. A crash between them can cause repeat commands. A stable commandId allows an external executor to deduplicate; the system does not claim exactly-once external side effects.

## Retrieval cache

Cache identity contains the authenticated owner, accessible knowledge bases, document and metadata filters, and a scoped database revision derived from document IDs, hashes, index state, and update time. Builds verify the revision on both sides of the load and discard changed snapshots.

The cache retains at most 32 entries and 32 million text characters with a 60-second TTL. Oversized corpora remain queryable but are not retained. The character budget is not a process-memory limit. Cold builds are serialized to avoid redundant index construction, which also makes unrelated cold requests wait. A future per-key singleflight design needs workload measurements and a regression suite before replacing this choice.

Index construction and ranking run in worker threads. At 100,000 chunks, warm lexical ranking still consumes measurable CPU; increasing cache capacity alone does not remove linear ranking work. See [Benchmarks](benchmarks/README.md) for measured results and limitations.

## Storage and module boundaries

Repository protocols separate domain behavior from SQLite/SQLAlchemy details. Alembic migrations include schema and approved-command recovery changes. Request schemas and the authentication router are separate modules; other business routers and resource assembly remain in the application factory and can be extracted gradually under contract tests.

SQLite is the implemented single-node store. Separate API and Kafka-worker processes both start the durable runtime. Multiple production replicas require a suitable database adapter and a defined scheduling/storage topology.

## Configuration boundary

The frontend receives only its public API URL. Private JSON is read in the Node build process through an allowlisted virtual module, with canary and bundle-scan verification. Git and Docker exclude local credentials and runtime data. Templates keep sensitive values empty.

## Verification and releases

Tests target failure recovery, ownership, offset ordering, lease fencing, migration backfill/rollback, cache invalidation, API/SSE behavior, and browser workflows. Real local Kafka/Redis tests complement unit doubles. Browser adapters verify protocol and persistence rather than model accuracy.

ECS release tooling registers a task definition for the selected SHA image, updates API and worker, waits for stability, checks running revisions and image names, and runs an application health smoke check. Failure attempts rollback to previous revisions and records failures. This release logic has fault-injection tests; actual AWS execution remains an operator action.

Evaluation executes against an explicitly selected API, with matched model/config/input metadata for a single-agent baseline. Unobserved token usage, cost, and call counts remain null; citation correctness requires independent annotation. Synthetic variants and operator-supplied version labels must not be presented as production incidents or server-certified metadata.
