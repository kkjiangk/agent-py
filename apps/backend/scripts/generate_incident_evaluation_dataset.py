from __future__ import annotations

import json
from pathlib import Path

SCENARIOS = [
    ("payment-api", "high_error_rate", "db_pool_exhaustion", "database pool saturation", 55),
    ("checkout-api", "latency_slo_breach", "cache_stampede", "cache miss burst", 45),
    ("order-worker", "queue_lag", "queue_backlog", "consumer lag", 60),
    ("inventory-api", "timeout_rate", "upstream_timeout", "upstream timeout", 50),
    ("pricing-api", "cpu_saturation", "hot_loop", "CPU saturation", 40),
    ("auth-api", "login_failures", "expired_signing_key", "signing-key expiry", 35),
    ("gateway", "five_xx_rate", "bad_deployment", "deployment regression", 50),
    ("notification-worker", "delivery_drop", "provider_rate_limit", "rate limiting", 45),
    ("catalog-api", "memory_pressure", "memory_leak", "heap growth", 65),
    ("search-api", "empty_results", "index_replica_lag", "replica lag", 40),
]


def main() -> None:
    output = Path(__file__).parents[3] / "evaluations" / "incidents-v1.jsonl"
    records: list[str] = []
    for scenario_index, (service, alert_type, root_cause, evidence, baseline_mttr) in enumerate(
        SCENARIOS, start=1
    ):
        for variant in range(1, 11):
            case_number = (scenario_index - 1) * 10 + variant
            record = {
                "datasetVersion": "incidents-v1",
                "caseId": f"incident-{case_number:03d}",
                "service": service,
                "alert": {
                    "alertType": alert_type,
                    "severity": "P1" if variant <= 3 else "P2",
                    "region": ["us-west-2", "us-east-1", "eu-west-1"][variant % 3],
                    "variant": variant,
                },
                "expectedRootCause": root_cause,
                "expectedEvidenceContains": [evidence],
                "baselineMttrMinutes": baseline_mttr + variant,
            }
            records.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(records) + "\n", encoding="utf-8")
    print(f"Generated {len(records)} cases at {output}")


if __name__ == "__main__":
    main()

