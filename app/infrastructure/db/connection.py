from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection
from uuid import uuid4
from datetime import datetime, timezone


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        try:
            yield conn
        finally:
            conn.close()

    def ping(self) -> None:
        with self.connection() as conn:
            conn.execute("select 1")

    def ensure_schema(self) -> None:
        migration_path = Path(__file__).with_name("migrations").joinpath("001_init.sql")
        sql = migration_path.read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(sql)
            self._migrate_users(conn)
            self._migrate_legacy_restaurants(conn)
            self._migrate_legacy_menu_tables(conn)
            self._migrate_admin_sessions(conn)
            conn.commit()

    def _columns(self, conn: Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()}

    def _migrate_users(self, conn: Connection) -> None:
        columns = self._columns(conn, "users")
        if "role" not in columns:
            conn.execute("alter table users add column role text not null default 'guest'")
            conn.execute("update users set role = case when is_admin = 1 then 'admin' else 'guest' end")

    def _migrate_legacy_restaurants(self, conn: Connection) -> None:
        columns = self._columns(conn, "restaurants")
        if "address" in columns:
            rows = conn.execute("select id, title, address, phone, created_at from restaurants").fetchall()
            for row in rows:
                exists = conn.execute("select 1 from branches where franchise_id = ? limit 1", (row["id"],)).fetchone()
                if exists:
                    continue
                conn.execute(
                    """
                    insert into branches (id, franchise_id, title, address, phone, position, created_at)
                    values (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (str(uuid4()), row["id"], row["title"], row["address"], row["phone"], row["created_at"]),
                )

    def _migrate_admin_sessions(self, conn: Connection) -> None:
        conn.execute(
            """
            create table if not exists admin_sessions (
                telegram_id integer primary key,
                chat_id integer not null,
                state text,
                draft_json text not null default '{}',
                history_json text not null default '[]',
                updated_at text not null
            )
            """
        )

    def _migrate_legacy_menu_tables(self, conn: Connection) -> None:
        categories_columns = self._columns(conn, "categories")
        dishes_columns = self._columns(conn, "dishes")
        if "branch_id" not in categories_columns:
            conn.execute("alter table categories add column branch_id text")
            rows = conn.execute("select id, restaurant_id from categories where branch_id is null").fetchall()
            for row in rows:
                branch = conn.execute("select id from branches where franchise_id = ? order by position limit 1", (row["restaurant_id"],)).fetchone()
                if branch:
                    conn.execute("update categories set branch_id = ? where id = ?", (branch["id"], row["id"]))
        if "branch_id" not in dishes_columns:
            conn.execute("alter table dishes add column branch_id text")
            rows = conn.execute("select id, restaurant_id from dishes where branch_id is null").fetchall()
            for row in rows:
                branch = conn.execute("select id from branches where franchise_id = ? order by position limit 1", (row["restaurant_id"],)).fetchone()
                if branch:
                    conn.execute("update dishes set branch_id = ? where id = ?", (branch["id"], row["id"]))
