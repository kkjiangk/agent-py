# Lexical retrieval benchmark

## Method

The benchmark compares rebuilding BM25L for every query with retaining and reusing the same index. It generates a deterministic operational-text corpus with seed 42 and runs ten queries at each scale. It checks exact ranking and score equivalence.

Measured locally on 2026-10-04 with Python 3.10.21 on macOS 15.4 ARM64. The checked-in [raw report](lexical-benchmark.json) records environment, parameters, cold build time, P50/P95, sequential throughput, Python allocation peak, and equivalence results.

| Chunks | Rebuild P50 / P95 | Reuse P50 / P95 | Cold build | Index allocation peak |
| --- | --- | --- | --- | --- |
| 1,000 | 5.551 / 6.833 ms | 0.723 / 0.908 ms | 55.563 ms | 1.75 MiB |
| 10,000 | 64.576 / 104.227 ms | 10.215 / 44.319 ms | 48.504 ms | 17.03 MiB |
| 100,000 | 991.515 / 1160.785 ms | 262.049 / 283.428 ms | 700.012 ms | 176.21 MiB |

Rankings and scores matched at every scale. The first cold build includes lazy scorer loading; cold times should not be interpreted as a monotonic size-only comparison. P95 uses the nearest-rank method, so ten repetitions provide a small-sample tail estimate.

## Reproduce

From the backend directory:

```bash
uv run python scripts/benchmark_lexical_retrieval.py \
  --sizes 1000 10000 100000 --repeats 10 --seed 42 \
  --output ../../evaluations/runs/lexical-benchmark.json
```

Keep rerun results separate from the recorded baseline until reviewed. Timing depends on machine load and environment.

## Interpretation

At 100,000 chunks, P95 improved by approximately 75.6% in this run. This is a single-process lexical microbenchmark, not an end-to-end RAG load test. It excludes database revision scans, Milvus, embeddings, reranking, network calls, and concurrent API traffic. Sequential queries-per-second cannot be treated as server throughput or a production SLA.

tracemalloc measures Python index allocations, not total process RSS or source-document storage. The cache text budget limits retained characters rather than memory bytes. Warm ranking still consumes CPU, and serialized cold builds can make unrelated cold requests wait. See [Engineering decisions](../engineering-quality.md).
