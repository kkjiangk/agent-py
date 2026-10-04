"""Client boundary for the local official MCP SSE server."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any, cast

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from super_ai.observability import elapsed_ms, emit_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str = "default"


@dataclass(frozen=True, slots=True)
class McpServerConnection:
    name: str
    url: str
    transport: str = "sse"
    timeout_seconds: float = 15
    retries: int = 1


class McpClientError(RuntimeError):
    pass


def create_current_time_tool() -> Any:
    """Create the explicit time tool used before time-range MCP queries."""
    from langchain_core.tools import StructuredTool

    def get_current_time() -> dict[str, object]:
        now = datetime.now(timezone.utc)
        return {"iso8601": now.isoformat(), "unixMilliseconds": int(now.timestamp() * 1000)}

    return StructuredTool.from_function(
        func=get_current_time,
        name="get_current_time",
        description="Return the current UTC time and Unix timestamp in milliseconds.",
    )


class LocalMcpClient:
    def __init__(
        self,
        endpoint: str | None = None,
        *,
        timeout_seconds: float = 15,
        retries: int = 1,
        connections: Sequence[McpServerConnection] | None = None,
    ) -> None:
        configured = list(connections or [])
        if not configured and endpoint is not None:
            configured = [
                McpServerConnection(
                    name="cls",
                    url=endpoint,
                    transport="sse",
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                )
            ]
        self._connections = tuple(configured)

    async def get_langchain_tools(self) -> list[Any]:
        await self.discover_tools()
        client = MultiServerMCPClient(
            cast(
                Any,
                {
                    connection.name: {
                        "transport": (
                            "http" if connection.transport == "streamable_http" else "sse"
                        ),
                        "url": connection.url,
                    }
                    for connection in self._connections
                },
            ),
            handle_tool_errors=False,
        )
        return await client.get_tools()

    async def discover_tools(self) -> list[McpToolDefinition]:
        definitions: list[McpToolDefinition] = []
        seen: set[str] = set()
        for connection in self._connections:
            result = await self._run_connection(
                connection,
                lambda session: session.list_tools(),
            )
            for tool in result.tools:
                if tool.name in seen:
                    raise McpClientError(f"Duplicate MCP tool name: {tool.name}")
                seen.add(tool.name)
                definitions.append(
                    McpToolDefinition(
                        tool.name,
                        tool.description or "MCP tool",
                        tool.inputSchema,
                        connection.name,
                    )
                )
        return definitions

    async def readiness(self) -> dict[str, object]:
        try:
            tools = await self.discover_tools()
        except McpClientError as exc:
            return {
                "ok": False,
                "endpoint": self._connections[0].url if self._connections else None,
                "toolCount": 0,
                "error": str(exc),
            }
        return {
            "ok": True,
            "endpoint": self._connections[0].url if self._connections else None,
            "toolCount": len(tools),
            "error": None,
        }

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        started_at = monotonic()
        emit_event(logger, "mcp.tool.started", toolName=name, argumentKeys=sorted(arguments))
        try:
            if len(self._connections) == 1:
                connection = self._connections[0]
                result = await self._run(
                    lambda session: session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(
                            seconds=connection.timeout_seconds
                        ),
                    )
                )
            else:
                matching = [tool for tool in await self.discover_tools() if tool.name == name]
                if len(matching) != 1:
                    raise McpClientError(f"MCP tool is unavailable or ambiguous: {name}")
                connection = next(
                    item for item in self._connections if item.name == matching[0].server_name
                )
                result = await self._run_connection(
                    connection,
                    lambda session: session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=timedelta(
                            seconds=connection.timeout_seconds
                        ),
                    ),
                )
        except Exception as exc:
            emit_event(
                logger,
                "mcp.tool.failed",
                toolName=name,
                errorCategory=exc.__class__.__name__,
                durationMs=elapsed_ms(started_at),
            )
            raise
        if result.isError:
            emit_event(
                logger,
                "mcp.tool.failed",
                toolName=name,
                errorCategory="McpToolError",
                durationMs=elapsed_ms(started_at),
            )
            raise McpClientError(f"MCP tool {name} returned an error")
        payload = [
            {"type": item.type, "text": getattr(item, "text", None)} for item in result.content
        ]
        emit_event(
            logger,
            "mcp.tool.completed",
            toolName=name,
            resultItemCount=len(payload),
            durationMs=elapsed_ms(started_at),
        )
        return payload

    async def _run(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        if len(self._connections) != 1:
            raise McpClientError("A single MCP connection is required for this operation.")
        return await self._run_connection(self._connections[0], operation)

    async def _run_connection(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        error: Exception | None = None
        for attempt in range(connection.retries + 1):
            try:
                if connection.transport == "streamable_http":
                    return await self._run_streamable_http(connection, operation)
                return await self._run_sse(connection, operation)
            except Exception as exc:
                error = exc
                if attempt < connection.retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
        raise McpClientError(f"MCP server unavailable at {connection.url}") from error

    async def _run_sse(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with sse_client(
            connection.url,
            timeout=connection.timeout_seconds,
            sse_read_timeout=connection.timeout_seconds,
        ) as streams:
            return await _run_initialized_session(
                streams[0],
                streams[1],
                operation,
                connection.timeout_seconds,
            )

    async def _run_streamable_http(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with httpx.AsyncClient(timeout=connection.timeout_seconds) as http_client:
            async with streamable_http_client(
                connection.url,
                http_client=http_client,
            ) as streams:
                return await _run_initialized_session(
                    streams[0],
                    streams[1],
                    operation,
                    connection.timeout_seconds,
                )


async def _run_initialized_session(
    read_stream: Any,
    write_stream: Any,
    operation: Callable[[Any], Awaitable[Any]],
    timeout_seconds: float,
) -> Any:
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        return await asyncio.wait_for(operation(session), timeout=timeout_seconds)
