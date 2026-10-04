"""Authentication service with password hashing and revocable bearer sessions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError

from super_ai.auth.repositories import AuthRepository, UserRecord

MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: UserRecord
    access_token: str
    token_type: str = "bearer"


class AuthError(RuntimeError):
    """Safe auth error with a shared API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthService:
    """Coordinate user credentials and session lifecycle."""

    def __init__(
        self,
        repository: AuthRepository,
        *,
        password_hash: PasswordHash | None = None,
    ) -> None:
        self._repository = repository
        self._password_hash = password_hash or PasswordHash.recommended()

    async def register(self, *, email: str, display_name: str, password: str) -> AuthResult:
        normalized_email = normalize_email(email)
        normalized_display_name = display_name.strip()
        _validate_registration(normalized_email, normalized_display_name, password)

        now = _utc_now()
        password_hash = self._password_hash.hash(password)
        try:
            user = await self._repository.create_user(
                user_id=f"user_{uuid4().hex}",
                email=normalized_email,
                display_name=normalized_display_name,
                password_hash=password_hash,
                created_at=now,
            )
        except IntegrityError as exc:
            raise AuthError("BUSINESS_CONFLICT", "A user with this email already exists.") from exc

        return await self._create_auth_result(user=user, created_at=now)

    async def login(self, *, email: str, password: str) -> AuthResult:
        normalized_email = normalize_email(email)
        user = await self._repository.find_user_by_email(normalized_email)
        if user is None:
            _verify_dummy_password(self._password_hash)
            raise AuthError("AUTH_INVALID_CREDENTIALS", "Invalid credentials.")
        if not self._password_hash.verify(password, user.password_hash):
            raise AuthError("AUTH_INVALID_CREDENTIALS", "Invalid credentials.")
        return await self._create_auth_result(user=user, created_at=_utc_now())

    async def authenticate_token(self, token: str) -> UserRecord:
        if not token.strip():
            raise AuthError("AUTH_UNAUTHENTICATED", "Authentication is required.")
        token_hash = hash_token(token)
        session = await self._repository.find_session_by_token_hash(token_hash)
        if session is None:
            raise AuthError("AUTH_UNAUTHENTICATED", "Authentication is required.")
        if session.revoked_at is not None:
            raise AuthError("AUTH_SESSION_REVOKED", "The authentication session has been revoked.")
        user = await self._repository.find_user_by_id(session.user_id)
        if user is None:
            raise AuthError("AUTH_UNAUTHENTICATED", "Authentication is required.")
        await self._repository.touch_session(session.id, _utc_now())
        return user

    async def logout(self, token: str) -> None:
        if not token.strip():
            raise AuthError("AUTH_UNAUTHENTICATED", "Authentication is required.")
        session = await self._repository.find_session_by_token_hash(hash_token(token))
        if session is None:
            raise AuthError("AUTH_UNAUTHENTICATED", "Authentication is required.")
        if session.revoked_at is not None:
            raise AuthError("AUTH_SESSION_REVOKED", "The authentication session has been revoked.")
        await self._repository.revoke_session(session.id, _utc_now())

    async def _create_auth_result(self, *, user: UserRecord, created_at: datetime) -> AuthResult:
        token = secrets.token_urlsafe(32)
        await self._repository.create_session(
            session_id=f"session_{uuid4().hex}",
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=created_at,
        )
        return AuthResult(user=user, access_token=token)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_registration(email: str, display_name: str, password: str) -> None:
    if "@" not in email or "." not in email.split("@")[-1]:
        raise AuthError("VALIDATION_INVALID_ARGUMENT", "A valid email is required.")
    if not display_name:
        raise AuthError("VALIDATION_MISSING_FIELD", "Display name is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError("VALIDATION_INVALID_ARGUMENT", "Password must be at least 8 characters.")


def _verify_dummy_password(password_hash: PasswordHash) -> None:
    dummy_hash = (
        "$argon2id$v=19$m=65536,t=3,p=4$wagCPXjifgvUFBzq4hqe3w"
        "$CYaIb8sB+wtD+Vu/P4uod1+Qof8h+1g7bbDlBID48Rc"
    )
    password_hash.verify("not-the-password", dummy_hash)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
