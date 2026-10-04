"""Owner-scoped user feedback validation and persistence service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from super_ai.memory.repositories import MemoryRepositories, UserFeedbackRecord

SUPPORTED_FEEDBACK_TARGETS = {
    "chat_message",
    "citation",
    "diagnostic_step",
    "diagnostic_report",
}
SUPPORTED_FEEDBACK_RATINGS = {"positive", "negative"}


@dataclass(frozen=True, slots=True)
class FeedbackError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class UserFeedbackService:
    def __init__(self, repositories: MemoryRepositories) -> None:
        self._repositories = repositories

    async def upsert(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
        subject_id: str | None,
        rating: str,
        reason: str | None,
        comment: str | None,
        correction: str | None,
    ) -> UserFeedbackRecord:
        if target_type not in SUPPORTED_FEEDBACK_TARGETS:
            raise FeedbackError("VALIDATION_INVALID_ARGUMENT", "Unsupported feedback target.")
        if rating not in SUPPORTED_FEEDBACK_RATINGS:
            raise FeedbackError("VALIDATION_INVALID_ARGUMENT", "Unsupported feedback rating.")
        normalized_subject = _optional_text(subject_id, 160)
        normalized_reason = _optional_text(reason, 80)
        normalized_comment = _optional_text(comment, 2000)
        normalized_correction = _optional_text(correction, 4000)
        await self._require_owned_target(
            owner_user_id=owner_user_id,
            target_type=target_type,
            target_id=target_id,
            subject_id=normalized_subject,
        )
        repository = self._repositories.feedback
        if repository is None:
            raise FeedbackError("SYSTEM_UNAVAILABLE", "Feedback storage is unavailable.")
        return await repository.upsert(
            owner_user_id=owner_user_id,
            feedback_id=f"feedback_{uuid4().hex}",
            target_type=target_type,
            target_id=target_id,
            subject_id=normalized_subject,
            rating=rating,
            reason=normalized_reason,
            comment=normalized_comment,
            correction=normalized_correction,
        )

    async def list_for_target(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
    ) -> list[UserFeedbackRecord]:
        if target_type not in SUPPORTED_FEEDBACK_TARGETS:
            raise FeedbackError("VALIDATION_INVALID_ARGUMENT", "Unsupported feedback target.")
        await self._require_owned_target(
            owner_user_id=owner_user_id,
            target_type=target_type,
            target_id=target_id,
            subject_id=None,
            allow_citation_collection=True,
        )
        repository = self._repositories.feedback
        if repository is None:
            raise FeedbackError("SYSTEM_UNAVAILABLE", "Feedback storage is unavailable.")
        return await repository.list_for_target(
            owner_user_id=owner_user_id,
            target_type=target_type,
            target_id=target_id,
        )

    async def delete(self, *, owner_user_id: str, feedback_id: str) -> bool:
        repository = self._repositories.feedback
        if repository is None:
            raise FeedbackError("SYSTEM_UNAVAILABLE", "Feedback storage is unavailable.")
        return await repository.delete(owner_user_id=owner_user_id, feedback_id=feedback_id)

    async def _require_owned_target(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
        subject_id: str | None,
        allow_citation_collection: bool = False,
    ) -> None:
        if target_type in {"chat_message", "citation"}:
            message = await self._repositories.chat.get_message(
                owner_user_id=owner_user_id,
                message_id=target_id,
            )
            if message is None or message.role != "assistant":
                raise FeedbackError("AUTH_FORBIDDEN", "Feedback target is not accessible.")
            if target_type == "citation" and not allow_citation_collection:
                if subject_id is None or not _message_has_citation(message.metadata, subject_id):
                    raise FeedbackError("AUTH_FORBIDDEN", "Feedback target is not accessible.")
            return
        if target_type == "diagnostic_step":
            target = await self._repositories.diagnostics.get_step(
                owner_user_id=owner_user_id,
                step_id=target_id,
            )
        else:
            target = await self._repositories.diagnostics.get_report(
                owner_user_id=owner_user_id,
                report_id=target_id,
            )
        if target is None:
            raise FeedbackError("AUTH_FORBIDDEN", "Feedback target is not accessible.")


def _message_has_citation(metadata: dict[str, object], citation_id: str) -> bool:
    citations = metadata.get("citations")
    if not isinstance(citations, list):
        return False
    for item in cast(list[object], citations):
        if isinstance(item, Mapping):
            mapping = cast(Mapping[object, object], item)
            if mapping.get("id") == citation_id:
                return True
    return False


def _optional_text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise FeedbackError("VALIDATION_INVALID_ARGUMENT", "Feedback text is too long.")
    return normalized
