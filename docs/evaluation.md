# Evaluation

The API-driven runner supports workflow diagnosis and a single-agent SSE baseline. It stores actual predictions, wall latency, tool observations, version declarations, and sanitized traces. The dataset contains 100 synthetic variants across ten categories.

Run instructions and all CLI options are documented in the repository's `evaluations/README.md`. The backend entry point is `scripts/run_incident_evaluation.py`; `scripts/evaluate_agents.py` aggregates reviewed JSONL output.

Use an isolated account and private token file. The runner calls actual configured model and tool services and can incur cost. Requests omit each case's expected answer; predictions require an explicit `ROOT_CAUSE: <code>` line. Paired baselines require matched input hash, dataset, model, and configuration.

Model usage is not fully exposed by the API. Calls, tokens, cost, and MTTR remain unmeasured unless independently captured; citation correctness needs annotation. Version labels are operator declarations. Unit tests and browser fixtures validate protocols, not model quality. Keep raw traces local because summaries can contain business data.

See [Testing](testing.md) and [Real integration fixtures](tutorials/real-log-and-alert.md).
