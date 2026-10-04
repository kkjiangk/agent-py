"""Reproducible BM25 microbenchmark; no cloud, database or model calls."""

from __future__ import annotations

import argparse
import gc
import json
import math
import platform
import random
import sys
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

from super_ai.retrieval.hybrid import Bm25Index, rank_bm25_documents


def benchmark(size: int, repeats: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    documents = [
        f"service-{rng.randrange(100)} API E_CONN_{rng.randrange(20)} "
        f"connection pool timeout request-{index} region-{rng.randrange(3)}"
        for index in range(size)
    ]
    queries = [f"E_CONN_{index % 20} pool timeout" for index in range(repeats)]
    started = perf_counter()
    index = Bm25Index(documents)
    cold_ms = (perf_counter() - started) * 1000
    baseline_ms: list[float] = []
    cached_ms: list[float] = []
    equivalent = True
    for query in queries:
        started = perf_counter()
        expected = rank_bm25_documents(query=query, documents=documents)
        baseline_ms.append((perf_counter() - started) * 1000)
        started = perf_counter()
        actual = index.rank(query=query)
        cached_ms.append((perf_counter() - started) * 1000)
        equivalent = equivalent and expected == actual
    del index
    gc.collect()
    tracemalloc.start()
    measured_index = Bm25Index(documents)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del measured_index
    return {
        "chunks": size,
        "repeats": repeats,
        "coldBuildMs": round(cold_ms, 3),
        "baselineP50Ms": round(median(baseline_ms), 3),
        "baselineP95Ms": round(sorted(baseline_ms)[math.ceil(0.95 * repeats) - 1], 3),
        "cachedP50Ms": round(median(cached_ms), 3),
        "cachedP95Ms": round(sorted(cached_ms)[math.ceil(0.95 * repeats) - 1], 3),
        "baselineQueriesPerSecond": round(repeats * 1000 / sum(baseline_ms), 2),
        "cachedQueriesPerSecond": round(repeats * 1000 / sum(cached_ms), 2),
        "indexPythonAllocationPeakMiB": round(peak_bytes / 1024**2, 2),
        "rankingsEquivalent": equivalent,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 2 or any(size < 1 for size in args.sizes):
        parser.error("Sizes must be positive and repeats must be at least two.")
    results: list[dict[str, object]] = []
    for size in args.sizes:
        result = benchmark(size, args.repeats, args.seed)
        results.append(result)
        print(json.dumps(result), flush=True)
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "seed": args.seed,
        "benchmark": "BM25L index build versus reused index",
        "limitations": "Single-process lexical microbenchmark; excludes database, Milvus, "
        "embedding, rerank, network and concurrent API traffic. Memory tracks Python index "
        "allocations, not total process RSS or source document storage.",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not all(result["rankingsEquivalent"] for result in results):
        raise SystemExit("Ranking regression detected.")


if __name__ == "__main__":
    main()
