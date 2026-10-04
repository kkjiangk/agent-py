"""ECS release orchestration with explicit image revisions and compensating rollback."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit
from urllib.request import urlopen

JsonObject = dict[str, object]
READ_ONLY_FIELDS = {
    "taskDefinitionArn",
    "revision",
    "status",
    "requiresAttributes",
    "compatibilities",
    "registeredAt",
    "registeredBy",
    "deregisteredAt",
}


class AwsCommands(Protocol):
    def run(self, arguments: Sequence[str]) -> JsonObject: ...


class AwsCli:
    def run(self, arguments: Sequence[str]) -> JsonObject:
        result = subprocess.run(
            ["aws", *arguments, "--output", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=660,
        )
        if result.returncode:
            # Never print task definitions, environment values, or CLI credentials.
            raise RuntimeError(f"AWS operation failed: {' '.join(arguments[:2])}.")
        if not result.stdout.strip():
            return {}
        value: object = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise RuntimeError("AWS returned a malformed response.")
        return cast(JsonObject, value)


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    service: str
    container: str


def object_value(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise RuntimeError("Expected an AWS response object.")
    return cast(JsonObject, value)


def objects(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        raise RuntimeError("Expected an AWS response list.")
    return [object_value(item) for item in cast(list[object], value)]


def render_task_definition(definition: JsonObject, *, container: str, image: str) -> JsonObject:
    rendered = copy.deepcopy(
        {key: value for key, value in definition.items() if key not in READ_ONLY_FIELDS}
    )
    matching = [
        item
        for item in objects(rendered.get("containerDefinitions"))
        if item.get("name") == container
    ]
    if len(matching) != 1:
        raise ValueError("Deployment container must match exactly one task container.")
    matching[0]["image"] = image
    return rendered


def smoke_check(url: str) -> None:
    parts = urlsplit(url)
    if (
        parts.username
        or parts.password
        or (
            parts.scheme != "https"
            and not (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"})
        )
    ):
        raise ValueError("Smoke check requires HTTPS or loopback HTTP without credentials.")
    with urlopen(url, timeout=15) as response:
        value: object = json.loads(response.read(65536))
        if response.status != 200 or object_value(value).get("ok") is not True:
            raise RuntimeError("Application smoke check failed.")


def deploy_release(
    aws: AwsCommands,
    *,
    cluster: str,
    targets: Sequence[DeploymentTarget],
    image: str,
    smoke: Callable[[], None],
) -> JsonObject:
    if (
        not cluster.strip()
        or not image.strip()
        or not targets
        or any(not target.service.strip() or not target.container.strip() for target in targets)
        or len({target.service for target in targets}) != len(targets)
    ):
        raise ValueError("Deployment services must be nonempty and unique.")
    previous: dict[str, str] = {}
    updated: list[str] = []
    revisions: dict[str, str] = {}
    try:
        # Snapshot every service before updating any of them.
        for target in targets:
            description = aws.run(
                [
                    "ecs",
                    "describe-services",
                    "--cluster",
                    cluster,
                    "--services",
                    target.service,
                ]
            )
            services = objects(description.get("services"))
            if description.get("failures") or len(services) != 1:
                raise RuntimeError("ECS service was not found.")
            previous[target.service] = str(services[0]["taskDefinition"])
        for target in targets:
            description = aws.run(
                [
                    "ecs",
                    "describe-task-definition",
                    "--task-definition",
                    previous[target.service],
                ]
            )
            rendered = render_task_definition(
                object_value(description.get("taskDefinition")),
                container=target.container,
                image=image,
            )
            registration = aws.run(
                [
                    "ecs",
                    "register-task-definition",
                    "--cli-input-json",
                    json.dumps(rendered),
                ]
            )
            revisions[target.service] = str(
                object_value(registration.get("taskDefinition"))["taskDefinitionArn"]
            )
            # Include attempted updates in rollback even if their acknowledgement is lost.
            updated.append(target.service)
            aws.run(
                [
                    "ecs",
                    "update-service",
                    "--cluster",
                    cluster,
                    "--service",
                    target.service,
                    "--task-definition",
                    revisions[target.service],
                    "--deployment-configuration",
                    json.dumps(
                        {
                            "deploymentCircuitBreaker": {"enable": True, "rollback": True},
                        }
                    ),
                ]
            )
        aws.run(["ecs", "wait", "services-stable", "--cluster", cluster, "--services", *updated])
        for target in targets:
            description = aws.run(
                [
                    "ecs",
                    "describe-services",
                    "--cluster",
                    cluster,
                    "--services",
                    target.service,
                ]
            )
            service = objects(description.get("services"))[0]
            if (
                service.get("taskDefinition") != revisions[target.service]
                or int(cast(int, service.get("desiredCount", 0))) < 1
            ):
                raise RuntimeError("ECS did not retain the requested release.")
            tasks = aws.run(
                [
                    "ecs",
                    "list-tasks",
                    "--cluster",
                    cluster,
                    "--service-name",
                    target.service,
                    "--desired-status",
                    "RUNNING",
                ]
            ).get("taskArns")
            if not isinstance(tasks, list) or not tasks:
                raise RuntimeError("Release has no running ECS tasks.")
            task_arns = [str(arn) for arn in cast(list[object], tasks)]
            # ECS describe-tasks accepts at most 100 tasks per request.
            for start in range(0, len(task_arns), 100):
                described = aws.run(
                    [
                        "ecs",
                        "describe-tasks",
                        "--cluster",
                        cluster,
                        "--tasks",
                        *task_arns[start : start + 100],
                    ]
                )
                if described.get("failures"):
                    raise RuntimeError("Running task verification failed.")
                running = objects(described.get("tasks"))
                if len(running) != len(task_arns[start : start + 100]):
                    raise RuntimeError("Running task verification returned incomplete results.")
                for task in running:
                    containers = [
                        item
                        for item in objects(task.get("containers"))
                        if item.get("name") == target.container
                    ]
                    if (
                        task.get("taskDefinitionArn") != revisions[target.service]
                        or len(containers) != 1
                        or containers[0].get("image") != image
                    ):
                        raise RuntimeError("Running task uses an unexpected image or revision.")
        smoke()
        return {"status": "deployed", "image": image, "taskDefinitions": revisions}
    except Exception as exc:
        rollback_failures: list[str] = []
        for service in reversed(updated):
            try:
                aws.run(
                    [
                        "ecs",
                        "update-service",
                        "--cluster",
                        cluster,
                        "--service",
                        service,
                        "--task-definition",
                        previous[service],
                    ]
                )
            except Exception:
                rollback_failures.append(service)
        if updated and not rollback_failures:
            try:
                aws.run(
                    ["ecs", "wait", "services-stable", "--cluster", cluster, "--services", *updated]
                )
            except Exception:
                rollback_failures.extend(updated)
        return {
            "status": "failed",
            "errorCategory": exc.__class__.__name__,
            "rollbackFailures": rollback_failures,
            "previousTaskDefinitions": previous,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in [
        "cluster",
        "api-service",
        "worker-service",
        "api-container",
        "worker-container",
        "image",
        "health-url",
    ]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--report", type=Path, default=Path("deployment-report.json"))
    args = parser.parse_args()
    result = deploy_release(
        AwsCli(),
        cluster=args.cluster,
        image=args.image,
        targets=[
            DeploymentTarget(args.api_service, args.api_container),
            DeploymentTarget(args.worker_service, args.worker_container),
        ],
        smoke=lambda: smoke_check(args.health_url),
    )
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    if result["status"] != "deployed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
