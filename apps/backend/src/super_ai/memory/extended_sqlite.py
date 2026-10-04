"""SQLite repositories for jobs, feedback, and managed MCP connections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from super_ai.memory.models import (
    BackgroundJobEventModel,
    BackgroundJobModel,
    McpConnectionModel,
    RemediationApprovalModel,
    UserFeedbackModel,
    utc_now,
)
from super_ai.memory.repositories import (
    BackgroundJobEventRecord,
    BackgroundJobRecord,
    JsonDict,
    McpConnectionRecord,
    RemediationApprovalRecord,
    UserFeedbackRecord,
)


class SQLiteRemediationApprovalRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        task_id: str,
        tool_name: str,
        arguments: JsonDict,
        rationale: str,
        risk_level: str,
    ) -> RemediationApprovalRecord:
        now = utc_now()
        row = RemediationApprovalModel(
            id=approval_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            tool_name=tool_name,
            arguments=arguments,
            rationale=rationale,
            risk_level=risk_level,
            status="pending",
            decision_note=None,
            decided_by_user_id=None,
            decided_at=None,
            dispatch_status="not_dispatched",
            dispatch_error=None,
            dispatched_at=None,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _remediation_approval_record(row)

    async def get(
        self, *, owner_user_id: str, approval_id: str
    ) -> RemediationApprovalRecord | None:
        stmt = select(RemediationApprovalModel).where(
            RemediationApprovalModel.id == approval_id,
            RemediationApprovalModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _remediation_approval_record(row) if row is not None else None

    async def list_for_task(
        self, *, owner_user_id: str, task_id: str
    ) -> list[RemediationApprovalRecord]:
        stmt = (
            select(RemediationApprovalModel)
            .where(
                RemediationApprovalModel.owner_user_id == owner_user_id,
                RemediationApprovalModel.task_id == task_id,
            )
            .order_by(RemediationApprovalModel.created_at.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_remediation_approval_record(row) for row in rows]

    async def transition_pending(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        status: str,
        decided_by_user_id: str,
        decision_note: str | None,
    ) -> RemediationApprovalRecord | None:
        now = utc_now()
        async with self._session_factory() as session:
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(RemediationApprovalModel)
                    .where(
                        RemediationApprovalModel.id == approval_id,
                        RemediationApprovalModel.owner_user_id == owner_user_id,
                        RemediationApprovalModel.status == "pending",
                    )
                    .values(
                        status=status,
                        decided_by_user_id=decided_by_user_id,
                        decision_note=decision_note,
                        decided_at=now,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                return None
            if status == "approved":
                # The durable job is our transactional outbox. Decision and
                # delivery intent commit together; no request-local task is lost.
                session.add(
                    BackgroundJobModel(
                        id=f"dispatch_{sha256(approval_id.encode()).hexdigest()[:32]}",
                        owner_user_id=owner_user_id,
                        kind="remediation_dispatch",
                        resource_type="remediation_approval",
                        resource_id=approval_id,
                        status="queued",
                        payload={"approvalId": approval_id},
                        attempt=0,
                        max_attempts=10,
                        timeout_seconds=30,
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.commit()
        return await self.get(owner_user_id=owner_user_id, approval_id=approval_id)

    async def update_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        dispatch_status: str,
        dispatch_error: str | None,
    ) -> RemediationApprovalRecord | None:
        now = utc_now()
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(RemediationApprovalModel).where(
                        RemediationApprovalModel.id == approval_id,
                        RemediationApprovalModel.owner_user_id == owner_user_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            row.dispatch_status = dispatch_status
            row.dispatch_error = dispatch_error
            row.dispatched_at = now if dispatch_status == "dispatched" else None
            row.updated_at = now
            await session.commit()
        return _remediation_approval_record(row)

    async def claim_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        lease_owner: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> RemediationApprovalRecord | None:
        async with self._session_factory() as session:
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(RemediationApprovalModel)
                    .where(
                        RemediationApprovalModel.id == approval_id,
                        RemediationApprovalModel.owner_user_id == owner_user_id,
                        RemediationApprovalModel.status == "approved",
                        RemediationApprovalModel.dispatch_status != "dispatched",
                        or_(
                            RemediationApprovalModel.dispatch_lease_expires_at.is_(None),
                            RemediationApprovalModel.dispatch_lease_expires_at <= now,
                        ),
                    )
                    .values(
                        dispatch_lease_owner=lease_owner,
                        dispatch_lease_expires_at=lease_expires_at,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                return None
            await session.commit()
        return await self.get(owner_user_id=owner_user_id, approval_id=approval_id)

    async def finish_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        lease_owner: str,
        dispatch_status: str,
        dispatch_error: str | None,
    ) -> RemediationApprovalRecord | None:
        now = utc_now()
        async with self._session_factory() as session:
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(RemediationApprovalModel)
                    .where(
                        RemediationApprovalModel.id == approval_id,
                        RemediationApprovalModel.owner_user_id == owner_user_id,
                        RemediationApprovalModel.dispatch_lease_owner == lease_owner,
                    )
                    .values(
                        dispatch_status=dispatch_status,
                        dispatch_error=dispatch_error,
                        dispatched_at=now if dispatch_status == "dispatched" else None,
                        dispatch_lease_owner=None,
                        dispatch_lease_expires_at=None,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                return None
            await session.commit()
        return await self.get(owner_user_id=owner_user_id, approval_id=approval_id)


class SQLiteBackgroundJobRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        kind: str,
        resource_type: str,
        resource_id: str,
        payload: JsonDict | None = None,
        max_attempts: int = 3,
        timeout_seconds: int = 900,
        retry_of_job_id: str | None = None,
        available_at: datetime | None = None,
    ) -> BackgroundJobRecord:
        now = utc_now()
        row = BackgroundJobModel(
            id=job_id,
            owner_user_id=owner_user_id,
            kind=kind,
            resource_type=resource_type,
            resource_id=resource_id,
            status="queued",
            payload=payload or {},
            attempt=0,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            available_at=available_at or now,
            lease_owner=None,
            lease_expires_at=None,
            cancel_requested_at=None,
            retry_of_job_id=retry_of_job_id,
            error_message=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _background_job_record(row)

    async def get(self, *, owner_user_id: str, job_id: str) -> BackgroundJobRecord | None:
        stmt = select(BackgroundJobModel).where(
            BackgroundJobModel.id == job_id,
            BackgroundJobModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _background_job_record(row) if row is not None else None

    async def find_for_resource(
        self,
        *,
        owner_user_id: str,
        resource_type: str,
        resource_id: str,
    ) -> BackgroundJobRecord | None:
        stmt = (
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.owner_user_id == owner_user_id,
                BackgroundJobModel.resource_type == resource_type,
                BackgroundJobModel.resource_id == resource_id,
            )
            .order_by(BackgroundJobModel.created_at.desc())
            .limit(1)
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).first()
        return _background_job_record(row) if row is not None else None

    async def list(self, *, owner_user_id: str) -> list[BackgroundJobRecord]:
        stmt = (
            select(BackgroundJobModel)
            .where(BackgroundJobModel.owner_user_id == owner_user_id)
            .order_by(BackgroundJobModel.created_at.desc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_background_job_record(row) for row in rows]

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> BackgroundJobRecord | None:
        claimed_at = now or utc_now()
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(BackgroundJobModel)
                .where(
                    BackgroundJobModel.status == "running",
                    BackgroundJobModel.lease_expires_at.is_not(None),
                    BackgroundJobModel.lease_expires_at < claimed_at,
                )
                .values(
                    status="queued",
                    lease_owner=None,
                    lease_expires_at=None,
                    available_at=claimed_at,
                    updated_at=claimed_at,
                )
            )
            stmt = (
                select(BackgroundJobModel)
                .where(
                    BackgroundJobModel.status == "queued",
                    BackgroundJobModel.available_at <= claimed_at,
                    BackgroundJobModel.cancel_requested_at.is_(None),
                )
                .order_by(
                    BackgroundJobModel.available_at.asc(),
                    BackgroundJobModel.created_at.asc(),
                )
                .limit(1)
            )
            row = (await session.scalars(stmt)).first()
            if row is None:
                return None
            row.status = "running"
            row.attempt += 1
            row.lease_owner = worker_id
            row.lease_expires_at = lease_expires_at
            row.started_at = row.started_at or claimed_at
            row.updated_at = claimed_at
        return _background_job_record(row)

    async def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: datetime,
    ) -> bool:
        stmt = select(BackgroundJobModel).where(
            BackgroundJobModel.id == job_id,
            BackgroundJobModel.status == "running",
            BackgroundJobModel.lease_owner == worker_id,
        )
        async with self._session_factory() as session, session.begin():
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return False
            row.lease_expires_at = lease_expires_at
            row.updated_at = utc_now()
        return True

    async def append_event(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        payload: JsonDict,
    ) -> BackgroundJobEventRecord:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            job = await session.get(BackgroundJobModel, job_id)
            if job is None or job.owner_user_id != owner_user_id:
                raise PermissionError(f"Background job is not accessible: {job_id}")
            latest = await session.scalar(
                select(func.max(BackgroundJobEventModel.sequence)).where(
                    BackgroundJobEventModel.job_id == job_id
                )
            )
            row = BackgroundJobEventModel(
                id=f"job_event_{job_id[-16:]}_{int(latest or 0) + 1}",
                job_id=job_id,
                owner_user_id=owner_user_id,
                sequence=int(latest or 0) + 1,
                payload=payload,
                created_at=now,
            )
            session.add(row)
        return _background_job_event_record(row)

    async def list_events(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        after_sequence: int = 0,
    ) -> list[BackgroundJobEventRecord]:
        if await self.get(owner_user_id=owner_user_id, job_id=job_id) is None:
            return []
        stmt = (
            select(BackgroundJobEventModel)
            .where(
                BackgroundJobEventModel.owner_user_id == owner_user_id,
                BackgroundJobEventModel.job_id == job_id,
                BackgroundJobEventModel.sequence > after_sequence,
            )
            .order_by(BackgroundJobEventModel.sequence.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_background_job_event_record(row) for row in rows]

    async def request_cancel(
        self, *, owner_user_id: str, job_id: str
    ) -> BackgroundJobRecord | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await session.get(BackgroundJobModel, job_id)
            if row is None or row.owner_user_id != owner_user_id:
                return None
            if row.status == "queued":
                row.status = "cancelled"
                row.completed_at = now
            elif row.status == "running":
                row.cancel_requested_at = now
            row.updated_at = now
        return _background_job_record(row)

    async def mark_succeeded(self, *, job_id: str, worker_id: str) -> BackgroundJobRecord | None:
        return await self._finish(job_id, worker_id, "succeeded", None)

    async def mark_cancelled(self, *, job_id: str, worker_id: str) -> BackgroundJobRecord | None:
        return await self._finish(job_id, worker_id, "cancelled", None)

    async def _finish(
        self, job_id: str, worker_id: str, status: str, error: str | None
    ) -> BackgroundJobRecord | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await session.get(BackgroundJobModel, job_id)
            if row is None or row.lease_owner != worker_id or row.status != "running":
                return None
            row.status = status
            row.error_message = error
            row.completed_at = now
            row.updated_at = now
            row.lease_owner = None
            row.lease_expires_at = None
        return _background_job_record(row)

    async def handle_failure(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        retry_at: datetime,
    ) -> BackgroundJobRecord | None:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await session.get(BackgroundJobModel, job_id)
            if row is None or row.lease_owner != worker_id or row.status != "running":
                return None
            row.error_message = error_message
            row.updated_at = now
            row.lease_owner = None
            row.lease_expires_at = None
            if row.attempt < row.max_attempts and row.cancel_requested_at is None:
                row.status = "queued"
                row.available_at = retry_at
            else:
                row.status = "failed"
                row.completed_at = now
        return _background_job_record(row)

    async def retry(
        self,
        *,
        owner_user_id: str,
        source_job_id: str,
        new_job_id: str,
    ) -> BackgroundJobRecord | None:
        source = await self.get(owner_user_id=owner_user_id, job_id=source_job_id)
        if source is None or source.status not in {"failed", "cancelled"}:
            return None
        return await self.enqueue(
            owner_user_id=owner_user_id,
            job_id=new_job_id,
            kind=source.kind,
            resource_type=source.resource_type,
            resource_id=source.resource_id,
            payload=source.payload,
            max_attempts=source.max_attempts,
            timeout_seconds=source.timeout_seconds,
            retry_of_job_id=source.id,
        )


class SQLiteUserFeedbackRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(
        self,
        *,
        owner_user_id: str,
        feedback_id: str,
        target_type: str,
        target_id: str,
        subject_id: str | None,
        rating: str,
        reason: str | None,
        comment: str | None,
        correction: str | None,
    ) -> UserFeedbackRecord:
        subject_key = subject_id or ""
        now = utc_now()
        stmt = select(UserFeedbackModel).where(
            UserFeedbackModel.owner_user_id == owner_user_id,
            UserFeedbackModel.target_type == target_type,
            UserFeedbackModel.target_id == target_id,
            UserFeedbackModel.subject_key == subject_key,
        )
        async with self._session_factory() as session, session.begin():
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                row = UserFeedbackModel(
                    id=feedback_id,
                    owner_user_id=owner_user_id,
                    target_type=target_type,
                    target_id=target_id,
                    subject_key=subject_key,
                    rating=rating,
                    reason=reason,
                    comment=comment,
                    correction=correction,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.rating = rating
                row.reason = reason
                row.comment = comment
                row.correction = correction
                row.updated_at = now
        return _user_feedback_record(row)

    async def list_for_target(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
    ) -> list[UserFeedbackRecord]:
        stmt = (
            select(UserFeedbackModel)
            .where(
                UserFeedbackModel.owner_user_id == owner_user_id,
                UserFeedbackModel.target_type == target_type,
                UserFeedbackModel.target_id == target_id,
            )
            .order_by(UserFeedbackModel.updated_at.desc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_user_feedback_record(row) for row in rows]

    async def delete(self, *, owner_user_id: str, feedback_id: str) -> bool:
        stmt = select(UserFeedbackModel).where(
            UserFeedbackModel.id == feedback_id,
            UserFeedbackModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session, session.begin():
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return False
            await session.delete(row)
        return True


class SQLiteMcpConnectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
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
        now = utc_now()
        row = McpConnectionModel(
            id=connection_id,
            owner_user_id=owner_user_id,
            name=name,
            transport=transport,
            url=url,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            retries=retries,
            last_check_ok=None,
            last_tool_count=None,
            last_tools=[],
            last_error=None,
            last_checked_at=None,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _mcp_connection_record(row)

    async def get(self, *, owner_user_id: str, connection_id: str) -> McpConnectionRecord | None:
        stmt = select(McpConnectionModel).where(
            McpConnectionModel.id == connection_id,
            McpConnectionModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _mcp_connection_record(row) if row is not None else None

    async def list(self, *, owner_user_id: str) -> list[McpConnectionRecord]:
        stmt = (
            select(McpConnectionModel)
            .where(McpConnectionModel.owner_user_id == owner_user_id)
            .order_by(McpConnectionModel.created_at.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_mcp_connection_record(row) for row in rows]

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
    ) -> McpConnectionRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await _scoped_connection(session, owner_user_id, connection_id)
            if row is None:
                return None
            row.name = name
            row.transport = transport
            row.url = url
            row.enabled = enabled
            row.timeout_seconds = timeout_seconds
            row.retries = retries
            row.updated_at = utc_now()
        return _mcp_connection_record(row)

    async def save_check(
        self,
        *,
        owner_user_id: str,
        connection_id: str,
        ok: bool,
        tools: list[JsonDict],
        error: str | None,
    ) -> McpConnectionRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await _scoped_connection(session, owner_user_id, connection_id)
            if row is None:
                return None
            row.last_check_ok = ok
            row.last_tool_count = len(tools)
            row.last_tools = tools
            row.last_error = error
            row.last_checked_at = utc_now()
            row.updated_at = utc_now()
        return _mcp_connection_record(row)

    async def delete(self, *, owner_user_id: str, connection_id: str) -> bool:
        stmt = select(McpConnectionModel).where(
            McpConnectionModel.id == connection_id,
            McpConnectionModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session, session.begin():
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return False
            await session.delete(row)
        return True


async def _scoped_connection(
    session: AsyncSession, owner_user_id: str, connection_id: str
) -> McpConnectionModel | None:
    stmt = select(McpConnectionModel).where(
        McpConnectionModel.id == connection_id,
        McpConnectionModel.owner_user_id == owner_user_id,
    )
    return (await session.scalars(stmt)).one_or_none()


def _background_job_record(row: BackgroundJobModel) -> BackgroundJobRecord:
    return BackgroundJobRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        kind=row.kind,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        status=row.status,
        payload=_json_dict(row.payload),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        timeout_seconds=row.timeout_seconds,
        available_at=_ensure_utc(row.available_at),
        lease_owner=row.lease_owner,
        lease_expires_at=_optional_utc(row.lease_expires_at),
        cancel_requested_at=_optional_utc(row.cancel_requested_at),
        retry_of_job_id=row.retry_of_job_id,
        error_message=row.error_message,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
        started_at=_optional_utc(row.started_at),
        completed_at=_optional_utc(row.completed_at),
    )


def _background_job_event_record(row: BackgroundJobEventModel) -> BackgroundJobEventRecord:
    return BackgroundJobEventRecord(
        id=row.id,
        job_id=row.job_id,
        owner_user_id=row.owner_user_id,
        sequence=row.sequence,
        payload=_json_dict(row.payload),
        created_at=_ensure_utc(row.created_at),
    )


def _user_feedback_record(row: UserFeedbackModel) -> UserFeedbackRecord:
    return UserFeedbackRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        target_type=row.target_type,
        target_id=row.target_id,
        subject_id=row.subject_key or None,
        rating=row.rating,
        reason=row.reason,
        comment=row.comment,
        correction=row.correction,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _mcp_connection_record(row: McpConnectionModel) -> McpConnectionRecord:
    return McpConnectionRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        name=row.name,
        transport=row.transport,
        url=row.url,
        enabled=row.enabled,
        timeout_seconds=row.timeout_seconds,
        retries=row.retries,
        last_check_ok=row.last_check_ok,
        last_tool_count=row.last_tool_count,
        last_tools=[_json_dict(item) for item in row.last_tools],
        last_error=row.last_error,
        last_checked_at=_optional_utc(row.last_checked_at),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _remediation_approval_record(
    row: RemediationApprovalModel,
) -> RemediationApprovalRecord:
    return RemediationApprovalRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        tool_name=row.tool_name,
        arguments=_json_dict(row.arguments),
        rationale=row.rationale,
        risk_level=row.risk_level,
        status=row.status,
        decision_note=row.decision_note,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=_optional_utc(row.decided_at),
        dispatch_status=row.dispatch_status,
        dispatch_error=row.dispatch_error,
        dispatched_at=_optional_utc(row.dispatched_at),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _json_dict(value: object) -> JsonDict:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in cast(Mapping[object, object], value).items()}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _ensure_utc(value) if value is not None else None
