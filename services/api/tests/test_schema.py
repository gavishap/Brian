"""The ORM mirrors the SQL migrations: fail fast when they drift apart."""

from __future__ import annotations

import asyncpg

from brian.models import Base


async def test_orm_matches_migrated_schema(database: str) -> None:
    conn = await asyncpg.connect(database)
    try:
        rows = await conn.fetch(
            "select table_name, column_name, is_nullable from information_schema.columns where table_schema = 'public'"
        )
    finally:
        await conn.close()
    db: dict[str, dict[str, bool]] = {}
    for row in rows:
        db.setdefault(row["table_name"], {})[row["column_name"]] = row["is_nullable"] == "YES"

    for table in Base.metadata.sorted_tables:
        assert table.name in db, f"table {table.name} missing from migrations"
        orm_columns = {c.name: c.nullable for c in table.columns}
        assert set(orm_columns) == set(db[table.name]), f"column mismatch in {table.name}"
        for name, nullable in orm_columns.items():
            if not table.columns[name].primary_key:
                assert bool(nullable) == db[table.name][name], f"{table.name}.{name} nullability differs"
    assert set(db) == {t.name for t in Base.metadata.sorted_tables}
