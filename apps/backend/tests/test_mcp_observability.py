from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from super_ai.mcp_client import LocalMcpClient


@dataclass(frozen=True, slots=True)
class FakeMcpContent:
    type: str
    text: str


@dataclass(frozen=True, slots=True)
class FakeMcpResult:
    isError: bool
    content: list[FakeMcpContent]


class FakeLocalMcpClient(LocalMcpClient):
    async def _run(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        del operation
        return FakeMcpResult(
            isError=False,
            content=[FakeMcpContent(type="text", text="mcp-output-secret")],
        )


@pytest.mark.asyncio
async def test_mcp_tool_logs_lifecycle_without_argument_values_or_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("super_ai.mcp_client").disabled = False
    caplog.set_level(logging.INFO, logger="super_ai.mcp_client")
    client = FakeLocalMcpClient("http://mcp.test/sse")

    result = await client.call_tool(
        "SearchLog",
        {"query": "query-secret", "topicId": "topic-secret"},
    )

    assert result == [{"type": "text", "text": "mcp-output-secret"}]
    events = [
        json.loads(record.message) for record in caplog.records if record.message.startswith("{")
    ]
    assert [event["event"] for event in events] == [
        "mcp.tool.started",
        "mcp.tool.completed",
    ]
    assert events[0]["argumentKeys"] == ["query", "topicId"]
    emitted = "\n".join(record.message for record in caplog.records)
    assert "query-secret" not in emitted
    assert "topic-secret" not in emitted
    assert "mcp-output-secret" not in emitted
