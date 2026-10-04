from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from super_ai.auth.service import AuthError, AuthService
from super_ai.auth.sqlite import SQLiteAuthRepository
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.models import AuthSessionModel, UserModel


@pytest.mark.asyncio
async def test_register_hashes_password_and_creates_revocable_session(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        service = AuthService(SQLiteAuthRepository(session_factory))

        auth_result = await service.register(
            email="Timi@Example.COM",
            display_name="Timi",
            password="correct horse battery staple",
        )

        async with session_factory() as session:
            user_stmt = select(UserModel).where(UserModel.email == "timi@example.com")
            user_row = (
                await session.scalars(user_stmt)
            ).one()
            session_row = (
                await session.scalars(
                    select(AuthSessionModel).where(AuthSessionModel.user_id == auth_result.user.id)
                )
            ).one()
    finally:
        await engine.dispose()

    assert auth_result.user.email == "timi@example.com"
    assert auth_result.access_token
    assert auth_result.token_type == "bearer"
    assert user_row.password_hash != "correct horse battery staple"
    assert user_row.password_hash.startswith("$argon2")
    assert session_row.token_hash != auth_result.access_token
    assert len(session_row.token_hash) == 64
    assert session_row.revoked_at is None


@pytest.mark.asyncio
async def test_duplicate_email_and_invalid_login_fail_safely(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        service = AuthService(SQLiteAuthRepository(create_memory_session_factory(engine)))
        await service.register(
            email="timi@example.com",
            display_name="Timi",
            password="correct horse battery staple",
        )

        with pytest.raises(AuthError) as duplicate_exc:
            await service.register(
                email="TIMI@example.com",
                display_name="Another Timi",
                password="correct horse battery staple",
            )
        with pytest.raises(AuthError) as invalid_exc:
            await service.login(email="timi@example.com", password="wrong password")
        with pytest.raises(AuthError) as unknown_exc:
            await service.login(email="nobody@example.com", password="wrong password")
    finally:
        await engine.dispose()

    assert duplicate_exc.value.code == "BUSINESS_CONFLICT"
    assert invalid_exc.value.code == "AUTH_INVALID_CREDENTIALS"
    assert unknown_exc.value.code == "AUTH_INVALID_CREDENTIALS"
    assert "password" not in str(invalid_exc.value).lower()


@pytest.mark.asyncio
async def test_token_validation_and_logout_revocation(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        service = AuthService(SQLiteAuthRepository(create_memory_session_factory(engine)))
        auth_result = await service.register(
            email="timi@example.com",
            display_name="Timi",
            password="correct horse battery staple",
        )

        current_user = await service.authenticate_token(auth_result.access_token)
        await service.logout(auth_result.access_token)
        with pytest.raises(AuthError) as revoked_exc:
            await service.authenticate_token(auth_result.access_token)
    finally:
        await engine.dispose()

    assert current_user.id == auth_result.user.id
    assert revoked_exc.value.code == "AUTH_SESSION_REVOKED"


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "auth.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
