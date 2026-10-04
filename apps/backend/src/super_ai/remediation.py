"""Human approval gate for dispatching remediation commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, cast
from uuid import uuid4

from super_ai.events import EventPublisher
from super_ai.events.config import EventIngestionSettings
from super_ai.events.models import BrokerRemediationCommand
from super_ai.memory.repositories import RemediationApprovalRecord, RemediationApprovalRepository
from super_ai.telemetry import get_tracer, record_span_error, safe_span_attributes


class RemediationDecisionError(RuntimeError):
    """Raised when an approval cannot transition safely."""


class RemediationDispatchBusyError(RuntimeError):
    """A concurrent dispatcher owns the command's renewable recovery boundary."""


class RemediationApprovalService:
    def __init__(
        self,
        *,
        repository: RemediationApprovalRepository,
        publisher: EventPublisher,
        settings: EventIngestionSettings,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._settings = settings

    async def decide(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        decision: str,
        decision_note: str | None,
    ) -> RemediationApprovalRecord:
        if decision not in {"approved", "rejected"}:
            raise RemediationDecisionError("Unsupported remediation decision.")
        current = await self._repository.get(
            owner_user_id=owner_user_id,
            approval_id=approval_id,
        )
        if current is None:
            raise RemediationDecisionError("Remediation approval was not found.")
        if current.status == "pending":
            transitioned = await self._repository.transition_pending(
                owner_user_id=owner_user_id,
                approval_id=approval_id,
                status=decision,
                decided_by_user_id=owner_user_id,
                decision_note=decision_note,
            )
            if transitioned is not None:
                current = transitioned
            else:
                refreshed = await self._repository.get(
                    owner_user_id=owner_user_id,
                    approval_id=approval_id,
                )
                if refreshed is None:
                    raise RemediationDecisionError("Remediation approval was not found.")
                current = refreshed
        if current.status != decision:
            raise RemediationDecisionError("Remediation approval already has another decision.")
        if decision == "rejected":
            if current.dispatch_status != "not_applicable":
                updated = await self._repository.update_dispatch(
                    owner_user_id=owner_user_id,
                    approval_id=approval_id,
                    dispatch_status="not_applicable",
                    dispatch_error=None,
                )
                if updated is not None:
                    current = updated
            return current
        if current.dispatch_status == "dispatched":
            return current
        return await self.dispatch_approved(owner_user_id=owner_user_id, approval_id=approval_id)

    async def dispatch_approved(
        self, *, owner_user_id: str, approval_id: str, require_completion: bool = False
    ) -> RemediationApprovalRecord:
        current = await self._repository.get(owner_user_id=owner_user_id, approval_id=approval_id)
        if current is None or current.status != "approved":
            raise RemediationDecisionError("Approved remediation was not found.")
        if current.dispatch_status == "dispatched":
            return current
        lease_owner = uuid4().hex
        now = datetime.now(timezone.utc)
        claimed = await self._repository.claim_dispatch(
            owner_user_id=owner_user_id,
            approval_id=approval_id,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=60),
            now=now,
        )
        if claimed is None:
            current = await self._repository.get(
                owner_user_id=owner_user_id, approval_id=approval_id
            )
            if current is None:
                raise RemediationDecisionError("Remediation approval was not found.")
            if require_completion and current.dispatch_status != "dispatched":
                raise RemediationDispatchBusyError("Remediation dispatch lease is busy.")
            return current
        return await self._dispatch(claimed, lease_owner=lease_owner)

    async def _dispatch(
        self, approval: RemediationApprovalRecord, *, lease_owner: str
    ) -> RemediationApprovalRecord:
        command = BrokerRemediationCommand(
            approvalId=approval.id,
            commandId=approval.id,
            diagnosticId=approval.task_id,
            ownerUserId=approval.owner_user_id,
            toolName=approval.tool_name,
            arguments=approval.arguments,
            riskLevel=cast(Literal["low", "medium", "high", "critical"], approval.risk_level),
            approvedByUserId=approval.decided_by_user_id,
            approvedAt=approval.decided_at.isoformat() if approval.decided_at else None,
        )
        with get_tracer().start_as_current_span(
            "agent.remediation.dispatch",
            attributes=safe_span_attributes(
                {
                    "approval.id": approval.id,
                    "diagnostic.id": approval.task_id,
                    "tool.name": approval.tool_name,
                    "risk.level": approval.risk_level,
                }
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                await self._publisher.publish(
                    topic=self._settings.remediation_topic,
                    key=approval.id,
                    value=command.model_dump_json(by_alias=True).encode(),
                )
            except Exception as exc:
                record_span_error(span, exc)
                await self._repository.finish_dispatch(
                    owner_user_id=approval.owner_user_id,
                    approval_id=approval.id,
                    lease_owner=lease_owner,
                    dispatch_status="failed",
                    dispatch_error=exc.__class__.__name__,
                )
                raise
        updated = await self._repository.finish_dispatch(
            owner_user_id=approval.owner_user_id,
            approval_id=approval.id,
            lease_owner=lease_owner,
            dispatch_status="dispatched",
            dispatch_error=None,
        )
        if updated is None:
            raise RemediationDecisionError("Remediation approval disappeared after dispatch.")
        return updated
