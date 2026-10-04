"""Owner-scoped MCP connection management and runtime resolution."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import uuid4

from super_ai.mcp_client import (
    LocalMcpClient,
    McpClientError,
    McpServerConnection,
    McpToolDefinition,
)
from super_ai.memory.repositories import (
    McpConnectionRecord,
    McpConnectionRepository,
    MemoryRepositories,
)

SUPPORTED_MCP_TRANSPORTS = {"sse", "streamable_http"}


@dataclass(frozen=True, slots=True)
class McpConnectionError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _ValidatedConnection:
    name: str
    transport: str
    url: str
    timeout_seconds: int
    retries: int


class McpConnectionService:
    def __init__(
        self,
        repositories: MemoryRepositories,
        *,
        default_url: str,
        default_timeout_seconds: int,
        default_retries: int,
    ) -> None:
        self._repositories = repositories
        self._default_url = default_url
        self._default_timeout_seconds = default_timeout_seconds
        self._default_retries = default_retries

    async def list(self, *, owner_user_id: str) -> list[McpConnectionRecord]:
        repository = self._repository()
        records = await repository.list(owner_user_id=owner_user_id)
        if records:
            return records
        await repository.create(
            owner_user_id=owner_user_id,
            connection_id=f"mcp_{uuid4().hex}",
            name="腾讯云 CLS",
            transport="sse",
            url=self._default_url,
            enabled=True,
            timeout_seconds=self._default_timeout_seconds,
            retries=self._default_retries,
        )
        return await repository.list(owner_user_id=owner_user_id)

    async def create(
        self,
        *,
        owner_user_id: str,
        name: str,
        transport: str,
        url: str,
        enabled: bool,
        timeout_seconds: int,
        retries: int,
    ) -> McpConnectionRecord:
        values = _validated_connection(name, transport, url, timeout_seconds, retries)
        return await self._repository().create(
            owner_user_id=owner_user_id,
            connection_id=f"mcp_{uuid4().hex}",
            enabled=enabled,
            name=values.name,
            transport=values.transport,
            url=values.url,
            timeout_seconds=values.timeout_seconds,
            retries=values.retries,
        )

    async def update(
        self,
        *,
        owner_user_id: str,
        connection_id: str,
        name: str,
        transport: str,
        url: str,
        enabled: bool,
        timeout_seconds: int,
        retries: int,
    ) -> McpConnectionRecord:
        values = _validated_connection(name, transport, url, timeout_seconds, retries)
        record = await self._repository().update(
            owner_user_id=owner_user_id,
            connection_id=connection_id,
            enabled=enabled,
            name=values.name,
            transport=values.transport,
            url=values.url,
            timeout_seconds=values.timeout_seconds,
            retries=values.retries,
        )
        if record is None:
            raise McpConnectionError("AUTH_FORBIDDEN", "MCP connection is not accessible.")
        return record

    async def delete(self, *, owner_user_id: str, connection_id: str) -> bool:
        return await self._repository().delete(
            owner_user_id=owner_user_id,
            connection_id=connection_id,
        )

    async def check(
        self, *, owner_user_id: str, connection_id: str
    ) -> tuple[McpConnectionRecord, list[McpToolDefinition]]:
        repository = self._repository()
        record = await repository.get(
            owner_user_id=owner_user_id,
            connection_id=connection_id,
        )
        if record is None:
            raise McpConnectionError("AUTH_FORBIDDEN", "MCP connection is not accessible.")
        client = _client_from_records([record])
        tools: list[McpToolDefinition] = []
        error: str | None = None
        try:
            tools = await client.discover_tools()
        except McpClientError:
            error = "MCP Server 不可用或工具发现失败。"
        updated = await repository.save_check(
            owner_user_id=owner_user_id,
            connection_id=connection_id,
            ok=error is None,
            tools=[_tool_payload(tool) for tool in tools],
            error=error,
        )
        if updated is None:
            raise McpConnectionError("AUTH_FORBIDDEN", "MCP connection is not accessible.")
        return updated, tools

    async def client_for_user(self, *, owner_user_id: str) -> LocalMcpClient:
        records = await self._repository().list(owner_user_id=owner_user_id)
        if not records:
            return LocalMcpClient(
                self._default_url,
                timeout_seconds=self._default_timeout_seconds,
                retries=self._default_retries,
            )
        return _client_from_records([record for record in records if record.enabled])

    def _repository(self) -> McpConnectionRepository:
        repository = self._repositories.mcp_connections
        if repository is None:
            raise McpConnectionError("SYSTEM_UNAVAILABLE", "MCP connection storage is unavailable.")
        return repository


def _validated_connection(
    name: str,
    transport: str,
    url: str,
    timeout_seconds: int,
    retries: int,
) -> _ValidatedConnection:
    normalized_name = name.strip()
    normalized_url = url.strip()
    parsed = urlsplit(normalized_url)
    if not normalized_name or len(normalized_name) > 120:
        raise McpConnectionError("VALIDATION_INVALID_ARGUMENT", "MCP 连接名称无效。")
    if transport not in SUPPORTED_MCP_TRANSPORTS:
        raise McpConnectionError("VALIDATION_INVALID_ARGUMENT", "MCP transport 无效。")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise McpConnectionError("VALIDATION_INVALID_ARGUMENT", "MCP URL 必须是安全的 HTTP 地址。")
    if not 1 <= timeout_seconds <= 300 or not 0 <= retries <= 5:
        raise McpConnectionError("VALIDATION_INVALID_ARGUMENT", "MCP 超时或重试参数无效。")
    return _ValidatedConnection(
        name=normalized_name,
        transport=transport,
        url=normalized_url,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def _client_from_records(records: list[McpConnectionRecord]) -> LocalMcpClient:
    return LocalMcpClient(
        connections=[
            McpServerConnection(
                name=record.id,
                url=record.url,
                transport=record.transport,
                timeout_seconds=record.timeout_seconds,
                retries=record.retries,
            )
            for record in records
        ]
    )


def _tool_payload(tool: McpToolDefinition) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
        "serverName": tool.server_name,
    }
