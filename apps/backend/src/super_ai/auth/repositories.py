"""Business-facing auth repository contracts and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    email: str
    display_name: str
    password_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSessionRecord:
    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None


class AuthRepository(Protocol):
    """Repository contract for user authentication."""

    async def create_user(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        password_hash: str,
        created_at: datetime,
    ) -> UserRecord:
        """Create a user."""
        ...

    async def find_user_by_email(self, email: str) -> UserRecord | None:
        """Find a user by normalized email."""
        ...

    async def find_user_by_id(self, user_id: str) -> UserRecord | None:
        """Find a user by id."""
        ...

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        created_at: datetime,
    ) -> AuthSessionRecord:
        """Create an auth session."""
        ...

    async def find_session_by_token_hash(self, token_hash: str) -> AuthSessionRecord | None:
        """Find an auth session by token hash."""
        ...

    async def touch_session(self, session_id: str, seen_at: datetime) -> AuthSessionRecord | None:
        """Update session last-seen time."""
        ...

    async def revoke_session(
        self,
        session_id: str,
        revoked_at: datetime,
    ) -> AuthSessionRecord | None:
        """Revoke an auth session."""
        ...
