"""Copy the SQLite database into the Postgres in DATABASE_URL (Phase 7 prep, 2026-11-23).

Every table, every row, the same ids; then each id counter is moved past the last row.
The target must be empty (or pass --replace to drop and recreate its tables first).

    docker compose run --rm --no-deps backend python -m backend.services.db_copy
    docker compose run --rm --no-deps backend python -m backend.services.db_copy --replace

Source: <data_dir>/app.db (the live file; SQLite gives one consistent read even while the app
runs), or --source PATH. Resume files and Milvus vectors are not in the database: not copied.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import Integer, create_engine, func, insert, inspect, select, text
from sqlmodel import SQLModel

from backend import db
from backend.config import data_dir

BATCH = 500


def _clean(v):
    """Postgres refuses the NUL character in text; SQLite stores it happily."""
    if isinstance(v, str):
        return v.replace("\x00", "")
    if isinstance(v, list):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    return v


def copy(source: Path, target_url: str, replace: bool = False, out=print) -> dict[str, int]:
    src = create_engine(f"sqlite:///{source}")
    dst = db.postgres_engine(target_url)
    if replace:
        SQLModel.metadata.drop_all(dst)
    SQLModel.metadata.create_all(dst)
    tables = SQLModel.metadata.sorted_tables
    with dst.connect() as c:
        busy = [t.name for t in tables if c.execute(select(func.count()).select_from(t)).scalar()]
    if busy:
        raise SystemExit(f"The Postgres database already has rows in: {', '.join(busy)}. "
                         "Use --replace to wipe it and copy again.")
    insp = inspect(src)
    have = set(insp.get_table_names())
    copied: dict[str, int] = {}
    with src.connect() as s, dst.begin() as d:
        for table in tables:
            if table.name not in have:
                continue
            src_cols = {c["name"] for c in insp.get_columns(table.name)}
            cols = [c for c in table.columns if c.name in src_cols]
            n, batch = 0, []
            for row in s.execute(select(*cols)).mappings():
                batch.append({k: _clean(v) for k, v in row.items()})
                if len(batch) >= BATCH:
                    d.execute(insert(table), batch)
                    n, batch = n + len(batch), []
            if batch:
                d.execute(insert(table), batch)
                n += len(batch)
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and isinstance(pk[0].type, Integer):
                d.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', '{pk[0].name}'), "
                    f"COALESCE((SELECT MAX(\"{pk[0].name}\") FROM \"{table.name}\"), 0) + 1, false)"))
            copied[table.name] = n
            out(f"{table.name}: {n}")
    return copied


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Copy the SQLite database into the Postgres in DATABASE_URL.")
    p.add_argument("--source", type=Path, default=None, help="SQLite file (default: <data_dir>/app.db)")
    p.add_argument("--replace", action="store_true", help="drop the Postgres tables first")
    a = p.parse_args(argv)
    url = db.postgres_url()
    if url is None:
        sys.exit("DATABASE_URL is blank: set it to the Postgres connection string first.")
    source = a.source or data_dir() / "app.db"
    if not source.is_file():
        sys.exit(f"No SQLite file at {source}.")
    copied = copy(source, url, a.replace)
    print(f"Done: {sum(copied.values())} rows in {len(copied)} tables.")


if __name__ == "__main__":
    main()
