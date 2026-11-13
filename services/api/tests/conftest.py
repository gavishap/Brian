"""Test fixtures: a throwaway Postgres database with the real Supabase migrations applied.

Point TEST_DATABASE_URL at any Postgres 15+ server you can create databases on, e.g.
`postgresql://postgres:postgres@127.0.0.1:5432/postgres` (CI) or the Supabase CLI's
`postgresql://postgres:postgres@127.0.0.1:54322/postgres`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import jwt
import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
AUTH_SHIM = Path(__file__).parent / "sql" / "supabase_auth_shim.sql"
JWT_SECRET = "test-secret-that-is-long-enough-for-hs256-signing"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:54329/postgres")
DB_NAME = f"brian_test_{uuid.uuid4().hex[:8]}"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{DB_NAME}"

# Settings are read from the environment, so configure it before the app is imported.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_URL,
        "SUPABASE_JWT_SECRET": JWT_SECRET,
        "LLM_ENABLED": "false",
        "PUSH_DRY_RUN": "true",
        "INTERNAL_API_KEY": "internal-test-key",
    }
)


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[str]:
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'create database "{DB_NAME}"')
    await admin.close()
    conn = await asyncpg.connect(TEST_URL)
    try:
        await conn.execute(AUTH_SHIM.read_text())
        for migration in MIGRATIONS:
            await conn.execute(migration.read_text())
    finally:
        await conn.close()
    yield TEST_URL

    from brian.db import get_engine

    await get_engine().dispose()
    admin = await asyncpg.connect(ADMIN_URL)
    await admin.execute(f'drop database if exists "{DB_NAME}" with (force)')
    await admin.close()


@pytest.fixture(autouse=True)
async def clean_tables(database: str) -> AsyncIterator[None]:
    yield
    conn = await asyncpg.connect(database)
    try:
        tables = await conn.fetch("select tablename from pg_tables where schemaname = 'public'")
        names = ", ".join(f"public.{t['tablename']}" for t in tables)
        await conn.execute(f"truncate {names}, auth.users restart identity cascade")
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    from brian.auth import get_token_verifier
    from brian.config import get_settings

    get_settings.cache_clear()
    get_token_verifier.cache_clear()
    yield
    get_settings.cache_clear()
    get_token_verifier.cache_clear()


def make_token(user_id: uuid.UUID, *, secret: str = JWT_SECRET, expires_in: int = 3600) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "email": f"{user_id.hex[:8]}@example.com",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


async def create_auth_user(database: str, *, display_name: str | None = "Alex") -> uuid.UUID:
    """Insert a Supabase auth user; the migration's trigger creates the profile."""
    user_id = uuid.uuid4()
    conn = await asyncpg.connect(database)
    try:
        await conn.execute(
            "insert into auth.users (id, email, raw_user_meta_data) values ($1, $2, $3::jsonb)",
            user_id,
            f"{user_id.hex[:8]}@example.com",
            json.dumps({"display_name": display_name} if display_name else {}),
        )
    finally:
        await conn.close()
    return user_id


class User:
    def __init__(self, user_id: uuid.UUID) -> None:
        self.id = user_id
        self.token = make_token(user_id)
        self.headers = {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
async def user(database: str) -> User:
    return User(await create_auth_user(database))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from brian.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as http:
        yield http
