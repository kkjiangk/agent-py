# Incident evaluation

`incidents-v1.jsonl` contains 100 versioned synthetic inputs across ten fault categories and contextual variants. It fixes the evaluation inputs; it is not a record of production incidents or achieved model scores.

## Execute a run

Use a separate evaluation account with relevant tool data and knowledge. Store its token in a private local file outside version control. These commands call the running API and its actual configured model/MCP services, create diagnosis records, and may incur model costs.

From the backend directory:

```bash
uv run python scripts/run_incident_evaluation.py ../../evaluations/incidents-v1.jsonl \
  --api http://127.0.0.1:8000 --token-file /absolute/private/evaluation-token.txt \
  --mode single-agent --model-version YOUR_MODEL_VERSION \
  --config-version YOUR_CONFIG_HASH --prompt-version single-agent-v1 \
  --output ../../evaluations/runs/baseline.jsonl

uv run python scripts/run_incident_evaluation.py ../../evaluations/incidents-v1.jsonl \
  --api http://127.0.0.1:8000 --token-file /absolute/private/evaluation-token.txt \
  --mode workflow --model-version YOUR_MODEL_VERSION \
  --config-version YOUR_CONFIG_HASH --prompt-version workflow-v1 \
  --baseline-results ../../evaluations/runs/baseline.jsonl \
  --output ../../evaluations/runs/workflow.jsonl
```

Remote execution requires `--allow-remote` and HTTPS. Outputs refuse overwriting and flush each result. Workflows persist diagnostics; single-agent runs delete their temporary chat session afterward. Workflow timeout requests cancellation of the created durable job.

## Predictions and pairing

The request contains the alert input and allowed label taxonomy, not the case-specific ground-truth answer. A report must include one unambiguous `ROOT_CAUSE: <code>` line. Missing, invalid, or conflicting labels become `unknown`; labels mentioned elsewhere in prose do not count as predictions.

`runMetadata` records mode, model/config/prompt version labels, and an input hash. Versions are operator-supplied declarations, marked as such. Baseline pairing requires matching dataset, expected label, model/config versions, input hash, and a single-agent mode record. The operator is responsible for matching external tool data and run conditions.

## Metrics

Required result identity fields are `datasetVersion`, `caseId`, `expectedRootCause`, and `predictedRootCause`; measured wall latency is `latencyMs`. The aggregator can additionally consume:

- independently annotated `citations[].correct`;
- observed `toolCalls[].success`;
- `agentCalls`, `promptTokens`, `completionTokens`, and `costUsd` when captured;
- `baselineCorrect`, `baselineMttrMinutes`, and `simulatedMttrMinutes` when independently measured.

The current API does not expose complete model usage to the runner. Unobserved calls, tokens, and cost are null, not zero. Citation existence is not citation correctness. Browser-test fixture output cannot serve as a model-quality result.

Aggregate reviewed run output from the backend directory:

```bash
uv run python scripts/evaluate_agents.py ../../evaluations/runs/workflow.jsonl \
  --json-output ../../evaluations/runs/report.json \
  --markdown-output ../../evaluations/runs/report.md
```

Reports include root-cause accuracy, annotated citation correctness, tool success, P50/P95, optional usage/cost, baseline improvement, and simulated MTTR. Missing measurements remain explicitly unmeasured.

## Trace handling and limitations

The runner omits raw tool input/output/payload and redacts common credential fields. Summaries can still contain business data; review them locally and keep raw runs outside Git. Actual model evaluation has not been included in the recorded unit/integration verification baseline.

Synthetic scenarios require relevant external evidence to support diagnosis. Ten categories with variants do not constitute 100 independent production incidents. Do not infer cost, accuracy improvement, or MTTR gains without the corresponding run data and annotation.
