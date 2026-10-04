"""SQLite-backed auth repository implementation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from super_ai.auth.repositories import AuthSessionRecord, UserRecord
from super_ai.memory.models import AuthSessionModel, UserModel


class SQLiteAuthRepository:
    """SQLite-compatible SQLAlchemy implementation of auth persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_user(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        password_hash: str,
        created_at: datetime,
    ) -> UserRecord:
        row = UserModel(
            id=user_id,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            created_at=created_at,
            updated_at=created_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise
        return _user_record(row)

    async def find_user_by_email(self, email: str) -> UserRecord | None:
        stmt = select(UserModel).where(UserModel.email == email)
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _user_record(row) if row is not None else None

    async def find_user_by_id(self, user_id: str) -> UserRecord | None:
        async with self._session_factory() as session:
            row = await session.get(UserModel, user_id)
        return _user_record(row) if row is not None else None

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        created_at: datetime,
    ) -> AuthSessionRecord:
        row = AuthSessionModel(
            id=session_id,
            user_id=user_id,
            token_hash=token_hash,
            created_at=created_at,
            last_seen_at=created_at,
            revoked_at=None,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _session_record(row)

    async def find_session_by_token_hash(self, token_hash: str) -> AuthSessionRecord | None:
        stmt = select(AuthSessionModel).where(AuthSessionModel.token_hash == token_hash)
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _session_record(row) if row is not None else None

    async def touch_session(self, session_id: str, seen_at: datetime) -> AuthSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(AuthSessionModel, session_id)
            if row is None:
                return None
            row.last_seen_at = seen_at
            await session.commit()
        return _session_record(row)

    async def revoke_session(
        self,
        session_id: str,
        revoked_at: datetime,
    ) -> AuthSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.get(AuthSessionModel, session_id)
            if row is None:
                return None
            row.revoked_at = revoked_at
            row.last_seen_at = revoked_at
            await session.commit()
        return _session_record(row)


def _user_record(row: UserModel) -> UserRecord:
    return UserRecord(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        password_hash=row.password_hash,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _session_record(row: AuthSessionModel) -> AuthSessionRecord:
    return AuthSessionRecord(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        created_at=_ensure_utc(row.created_at),
        last_seen_at=_ensure_utc(row.last_seen_at),
        revoked_at=_ensure_utc_optional(row.revoked_at),
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_utc_optional(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_utc(value)
