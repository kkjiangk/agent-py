"""Publish the explicit e-commerce quant-service fixture to local Alertmanager."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from super_ai.aiops.fixtures import (
    build_java_ecommerce_alert_payload,
    build_quant_alert_payload,
)
from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_str,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("java-ecommerce", "quant"),
        default="java-ecommerce",
    )
    args = parser.parse_args()
    config = project_config_section("prometheusAlerts")
    alerts_api = _local_alertmanager_api(config)
    timeout_seconds = required_float(config, "timeoutSeconds")
    now = datetime.now(timezone.utc)
    payload = (
        build_java_ecommerce_alert_payload(now)
        if args.profile == "java-ecommerce"
        else build_quant_alert_payload(now)
    )
    request = Request(
        alerts_api,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status not in {200, 201, 202}:
                raise SystemExit(f"Alertmanager returned HTTP {response.status}.")
    except (HTTPError, URLError) as exc:
        raise SystemExit("Unable to publish the local Alertmanager fixture.") from exc
    print(f"Published {len(payload)} {args.profile} alerts to local Alertmanager.")


def _local_alertmanager_api(config: object) -> str:
    if not isinstance(config, Mapping):
        raise ProjectConfigurationError("Alert configuration must be an object.")
    sources = config.get("sources")
    if not isinstance(sources, list):
        raise ProjectConfigurationError("Alert sources must be a list.")
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        if source.get("id") == "local-alertmanager":
            return required_str(source, "alertsApi")
    raise ProjectConfigurationError("Local Alertmanager source is not configured.")


if __name__ == "__main__":
    main()
