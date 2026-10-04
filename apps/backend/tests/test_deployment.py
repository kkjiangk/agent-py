from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from super_ai.deployment import DeploymentTarget, deploy_release, objects, render_task_definition


class FakeAws:
    def __init__(self, *, unexpected_image: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.current = {"api": "old-api", "worker": "old-worker"}
        self.images: dict[str, str] = {}
        self.unexpected_image = unexpected_image

    def run(self, arguments: Sequence[str]) -> dict[str, object]:
        args = list(arguments)
        self.calls.append(args)
        operation = args[1]
        if operation == "describe-services":
            service = args[args.index("--services") + 1]
            return {"services": [{"taskDefinition": self.current[service], "desiredCount": 1}]}
        if operation == "describe-task-definition":
            service = args[-1].split("-")[-1]
            return {
                "taskDefinition": {
                    "family": service,
                    "revision": 1,
                    "status": "ACTIVE",
                    "taskDefinitionArn": args[-1],
                    "containerDefinitions": [{"name": service, "image": "old:sha"}],
                }
            }
        if operation == "register-task-definition":
            rendered: dict[str, object] = json.loads(args[-1])
            service = str(rendered["family"])
            self.images[service] = str(objects(rendered["containerDefinitions"])[0]["image"])
            return {"taskDefinition": {"taskDefinitionArn": f"new-{service}"}}
        if operation == "update-service":
            service = args[args.index("--service") + 1]
            self.current[service] = args[args.index("--task-definition") + 1]
            return {}
        if operation == "list-tasks":
            return {"taskArns": [args[args.index("--service-name") + 1]]}
        if operation == "describe-tasks":
            service = args[-1]
            return {
                "tasks": [
                    {
                        "taskDefinitionArn": self.current[service],
                        "containers": [
                            {
                                "name": service,
                                "image": (
                                    "wrong:sha" if self.unexpected_image else self.images[service]
                                ),
                            }
                        ],
                    }
                ]
            }
        if operation == "wait":
            return {}
        raise AssertionError(f"Unexpected operation: {operation}")


TARGETS = [DeploymentTarget("api", "api"), DeploymentTarget("worker", "worker")]


def test_task_definition_changes_only_selected_container_and_removes_read_only_fields() -> None:
    original: dict[str, object] = {
        "family": "api",
        "taskDefinitionArn": "old",
        "revision": 4,
        "containerDefinitions": [
            {"name": "api", "image": "old"},
            {"name": "sidecar", "image": "keep"},
        ],
    }
    rendered = render_task_definition(original, container="api", image="repo:new-sha")
    assert rendered == {
        "family": "api",
        "containerDefinitions": [
            {"name": "api", "image": "repo:new-sha"},
            {"name": "sidecar", "image": "keep"},
        ],
    }
    assert original["revision"] == 4
    with pytest.raises(ValueError):
        render_task_definition(original, container="missing", image="repo:new-sha")


def test_release_updates_and_verifies_both_services() -> None:
    aws = FakeAws()
    smoke_calls: list[bool] = []
    report = deploy_release(
        aws,
        cluster="test",
        targets=TARGETS,
        image="repo:new-sha",
        smoke=lambda: smoke_calls.append(True),
    )
    assert report["status"] == "deployed"
    assert aws.current == {"api": "new-api", "worker": "new-worker"}
    assert aws.images == {"api": "repo:new-sha", "worker": "repo:new-sha"}
    assert smoke_calls == [True]


def test_failed_smoke_check_restores_both_previous_revisions() -> None:
    aws = FakeAws()

    def fail() -> None:
        raise RuntimeError("Injected failed smoke check")

    report = deploy_release(aws, cluster="test", targets=TARGETS, image="repo:new-sha", smoke=fail)
    assert report["status"] == "failed"
    assert report["rollbackFailures"] == []
    assert aws.current == {"api": "old-api", "worker": "old-worker"}


def test_running_image_mismatch_rolls_back_before_smoke_check() -> None:
    aws = FakeAws(unexpected_image=True)
    smoke_calls: list[bool] = []
    report = deploy_release(
        aws,
        cluster="test",
        targets=TARGETS,
        image="repo:new-sha",
        smoke=lambda: smoke_calls.append(True),
    )
    assert report["status"] == "failed"
    assert smoke_calls == []
    assert aws.current == {"api": "old-api", "worker": "old-worker"}
