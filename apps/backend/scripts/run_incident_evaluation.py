"""Explicitly execute workflow or single-Agent evaluations; never fabricates usage metrics."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal, cast

import httpx

from super_ai.deployment import object_value
from super_ai.evaluation import load_evaluation_records
from super_ai.evaluation_runner import (
    EvaluationRunSettings,
    IncidentEvaluationRunner,
    validate_evaluation_endpoint,
)


def load_cases(path: Path) -> list[dict[str, object]]:
    cases = [
        object_value(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or len({case.get("datasetVersion") for case in cases}) != 1:
        raise ValueError("Dataset must contain one nonempty version.")
    identifiers = [case.get("caseId") for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Dataset case IDs must be unique.")
    for case in cases:
        for field in ("datasetVersion", "caseId", "expectedRootCause", "service"):
            value = case.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Dataset requires nonempty {field}.")
        object_value(case.get("alert"))
    return cases


async def run(args: argparse.Namespace) -> None:
    validate_evaluation_endpoint(args.api, allow_remote=args.allow_remote)
    token = args.token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Token file must contain a valid evaluation account token.")
    cases = load_cases(args.dataset)
    allowed_codes = sorted({str(case["expectedRootCause"]) for case in cases})
    settings = EvaluationRunSettings(
        mode=cast(Literal["workflow", "single-agent"], args.mode),
        model_version=args.model_version,
        config_version=args.config_version,
        prompt_version=args.prompt_version,
        timeout_seconds=args.timeout,
    )
    baseline = (
        {str(record["caseId"]): record for record in load_evaluation_records(args.baseline_results)}
        if args.baseline_results is not None
        else {}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse overwriting an earlier run; every result is flushed for interruption recovery.
    with args.output.open("x", encoding="utf-8") as output:
        async with httpx.AsyncClient(
            base_url=args.api.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            follow_redirects=False,
        ) as client:
            runner = IncidentEvaluationRunner(client, settings)
            for case in cases:
                result = await runner.run_case(case, allowed_codes=allowed_codes)
                paired = baseline.get(str(case["caseId"]))
                if paired is not None:
                    metadata = object_value(paired.get("runMetadata"))
                    current = object_value(result["runMetadata"])
                    if (
                        paired["datasetVersion"] != result["datasetVersion"]
                        or paired["expectedRootCause"] != result["expectedRootCause"]
                        or any(
                            metadata.get(key) != current.get(key)
                            for key in ("modelVersion", "configVersion", "inputSha256")
                        )
                        or metadata.get("mode") != "single-agent"
                    ):
                        raise ValueError("Baseline version, input, model or configuration differs.")
                    result["baselineCorrect"] = (
                        paired["predictedRootCause"] == paired["expectedRootCause"]
                    )
                output.write(json.dumps(result, ensure_ascii=False) + "\n")
                output.flush()
                print(f"{case['caseId']}: {result['status']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--mode", choices=["workflow", "single-agent"], required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--config-version", required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--baseline-results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("Timeout must be positive.")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
