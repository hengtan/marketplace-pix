from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
            break
    return {**values, **os.environ}


def database_url(db: str) -> str:
    env = _read_env()
    return (
        f"postgresql+asyncpg://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env.get('POSTGRES_HOST', 'localhost')}:{env.get('POSTGRES_PORT', '5433')}/{db}"
    )


async def ensure_database(name: str) -> None:
    admin = create_async_engine(
        database_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": name}
        )
        if not exists:
            await conn.execute(text(f'create database "{name}"'))
    await admin.dispose()


def build_engine(name: str) -> AsyncEngine:
    return create_async_engine(database_url(name), poolclass=NullPool)
