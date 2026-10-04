"""Session-scoped chat context measurement and compression."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, cast

from langchain_core.messages.utils import count_tokens_approximately

from super_ai.llm import LlmProvider
from super_ai.memory.repositories import (
    ChatMessageRecord,
    ChatSessionRecord,
    MemoryRepositories,
)

ChatMemoryMode = Literal["every_30_turns", "context_70_percent", "manual"]
SUPPORTED_CHAT_MEMORY_MODES: tuple[ChatMemoryMode, ...] = (
    "every_30_turns",
    "context_70_percent",
    "manual",
)
AUTO_CONTEXT_THRESHOLD_PERCENT = 70.0
HARD_CONTEXT_THRESHOLD_PERCENT = 95.0


class ChatContextLimitReached(RuntimeError):
    """Raised before persistence when a candidate message exceeds the hard budget."""


@dataclass(frozen=True, slots=True)
class PreparedChatContext:
    session: ChatSessionRecord
    messages: tuple[ChatMessageRecord, ...]
    system_prompt: str


class ChatMemoryService:
    """Apply a session memory policy without deleting persisted history."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        llm_provider: LlmProvider,
        context_window_tokens: int,
    ) -> None:
        if context_window_tokens <= 0:
            raise ValueError("context_window_tokens must be positive")
        self._repositories = repositories
        self._llm_provider = llm_provider
        self.context_window_tokens = context_window_tokens

    async def prepare_message(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        history: list[ChatMessageRecord],
        system_prompt: str,
        content: str,
    ) -> PreparedChatContext:
        current = session
        uncompressed = history[current.compacted_message_count :]
        candidate = _candidate_user_message(current, owner_user_id, content)
        candidate_messages = [*uncompressed, candidate]
        candidate_tokens = estimate_context_tokens(
            system_prompt=system_prompt,
            memory_summary=current.memory_summary,
            messages=candidate_messages,
        )
        completed_turns = sum(message.role == "assistant" for message in uncompressed)
        should_compact = (
            current.memory_mode == "every_30_turns" and completed_turns >= 30
        ) or (
            current.memory_mode == "context_70_percent"
            and _usage_percent(candidate_tokens, self.context_window_tokens)
            >= AUTO_CONTEXT_THRESHOLD_PERCENT
        )
        if should_compact and uncompressed:
            current = await self._compact_messages(
                owner_user_id=owner_user_id,
                session=current,
                messages=uncompressed,
                system_prompt=system_prompt,
            )
            candidate_messages = [candidate]
            candidate_tokens = estimate_context_tokens(
                system_prompt=system_prompt,
                memory_summary=current.memory_summary,
                messages=candidate_messages,
            )

        if (
            _usage_percent(candidate_tokens, self.context_window_tokens)
            >= HARD_CONTEXT_THRESHOLD_PERCENT
        ):
            raise ChatContextLimitReached

        updated = await self._repositories.chat.update_memory_state(
            owner_user_id=owner_user_id,
            session_id=current.id,
            context_tokens=candidate_tokens,
        )
        return PreparedChatContext(
            session=updated or current,
            messages=tuple(candidate_messages),
            system_prompt=_prompt_with_memory(system_prompt, current.memory_summary),
        )

    async def refresh_usage(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        history: list[ChatMessageRecord],
        system_prompt: str,
    ) -> ChatSessionRecord:
        tokens = estimate_context_tokens(
            system_prompt=system_prompt,
            memory_summary=session.memory_summary,
            messages=history[session.compacted_message_count :],
        )
        updated = await self._repositories.chat.update_memory_state(
            owner_user_id=owner_user_id,
            session_id=session.id,
            context_tokens=tokens,
        )
        return updated or session

    async def set_mode(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        mode: ChatMemoryMode,
        history: list[ChatMessageRecord],
        system_prompt: str,
    ) -> ChatSessionRecord:
        updated = await self._repositories.chat.update_memory_state(
            owner_user_id=owner_user_id,
            session_id=session.id,
            memory_mode=mode,
        )
        current = updated or session
        if mode == "manual":
            return await self.compact(
                owner_user_id=owner_user_id,
                session=current,
                history=history,
                system_prompt=system_prompt,
            )
        return await self.refresh_usage(
            owner_user_id=owner_user_id,
            session=current,
            history=history,
            system_prompt=system_prompt,
        )

    async def compact(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        history: list[ChatMessageRecord],
        system_prompt: str,
    ) -> ChatSessionRecord:
        uncompressed = history[session.compacted_message_count :]
        if not uncompressed:
            return await self.refresh_usage(
                owner_user_id=owner_user_id,
                session=session,
                history=history,
                system_prompt=system_prompt,
            )
        return await self._compact_messages(
            owner_user_id=owner_user_id,
            session=session,
            messages=uncompressed,
            system_prompt=system_prompt,
        )

    async def _compact_messages(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        messages: list[ChatMessageRecord],
        system_prompt: str,
    ) -> ChatSessionRecord:
        transcript = "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )
        prompt = (
            "请将以下对话压缩为可供后续模型继续对话的中文记忆摘要。保留用户目标、"
            "明确事实、偏好、决策、未完成事项、工具结果和引用来源；删除寒暄与重复内容。"
            "只输出摘要正文，不超过 1200 个汉字。\n\n"
            f"已有摘要：\n{session.memory_summary or '无'}\n\n"
            f"新增对话：\n{transcript}"
        )
        response = await self._llm_provider.create_chat_model().ainvoke(prompt)
        summary = _extract_model_text(response).strip()
        if not summary:
            raise RuntimeError("The model returned an empty memory summary.")
        compacted_count = session.compacted_message_count + len(messages)
        tokens = estimate_context_tokens(
            system_prompt=system_prompt,
            memory_summary=summary,
            messages=[],
        )
        updated = await self._repositories.chat.update_memory_state(
            owner_user_id=owner_user_id,
            session_id=session.id,
            memory_summary=summary,
            compacted_message_count=compacted_count,
            context_tokens=tokens,
            last_compacted_at=datetime.now(timezone.utc),
        )
        return updated or session


def estimate_context_tokens(
    *,
    system_prompt: str,
    memory_summary: str | None,
    messages: list[ChatMessageRecord],
) -> int:
    values: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if memory_summary:
        values.append({"role": "system", "content": _memory_instruction(memory_summary)})
    values.extend(
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant"}
    )
    return int(count_tokens_approximately(cast(Any, values)))


def memory_payload(session: ChatSessionRecord, context_window_tokens: int) -> dict[str, object]:
    return {
        "mode": session.memory_mode,
        "contextTokens": session.context_tokens,
        "contextWindowTokens": context_window_tokens,
        "contextUsagePercent": _usage_percent(
            session.context_tokens, context_window_tokens
        ),
        "compactedMessageCount": session.compacted_message_count,
        "lastCompactedAt": (
            session.last_compacted_at.isoformat()
            if session.last_compacted_at is not None
            else None
        ),
        "canCompact": session.context_tokens > 0,
    }


def _candidate_user_message(
    session: ChatSessionRecord, owner_user_id: str, content: str
) -> ChatMessageRecord:
    return ChatMessageRecord(
        id="candidate",
        owner_user_id=owner_user_id,
        session_id=session.id,
        role="user",
        content=content,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )


def _usage_percent(tokens: int, window: int) -> float:
    return round(min(100.0, tokens / window * 100), 1)


def _memory_instruction(summary: str) -> str:
    return f"以下是此前对话的压缩记忆，请作为真实会话上下文继续回答：\n{summary}"


def _prompt_with_memory(system_prompt: str, summary: str | None) -> str:
    return (
        f"{system_prompt}\n\n{_memory_instruction(summary)}"
        if summary
        else system_prompt
    )


def _extract_model_text(value: object) -> str:
    content = getattr(value, "content", value)
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
        parts: list[str] = []
        for item in cast(Sequence[object], content):
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                text = cast(Mapping[object, object], item).get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""
