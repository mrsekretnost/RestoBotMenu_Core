from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.domain.models.restaurant import Branch, Category, Dish, Franchise, User
from app.infrastructure.db.connection import Database


OWNER_ROLE = "owner"
ADMIN_ROLE = "admin"
GUEST_ROLE = "guest"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RestaurantRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_or_create_user(self, telegram_id: int, username: str | None, first_name: str | None) -> User:
        with self.database.connection() as conn:
            row = conn.execute("select * from users where telegram_id = ?", (telegram_id,)).fetchone()
            if row:
                role = row["role"]
                conn.execute(
                    "update users set username = ?, first_name = ?, role = ?, is_admin = ? where telegram_id = ?",
                    (username, first_name, role, 1 if role in {OWNER_ROLE, ADMIN_ROLE} else 0, telegram_id),
                )
                conn.commit()
                row = conn.execute("select * from users where telegram_id = ?", (telegram_id,)).fetchone()
            else:
                user_id = str(uuid4())
                conn.execute(
                    "insert into users (id, telegram_id, username, first_name, role, is_admin, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, telegram_id, username, first_name, GUEST_ROLE, 0, now_iso()),
                )
                conn.commit()
                row = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
        return self._user(row)

    def get_user_by_id(self, user_id: UUID) -> User | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from users where id = ?", (str(user_id),)).fetchone()
        return self._user(row) if row else None

    def owner_exists(self) -> bool:
        with self.database.connection() as conn:
            row = conn.execute("select 1 from users where role = ? limit 1", (OWNER_ROLE,)).fetchone()
        return row is not None

    def get_or_create_owner_setup_started_at(self) -> datetime:
        started = self.get_state("owner_setup_started_at")
        if started:
            return parse_dt(started)
        value = now_iso()
        self.set_state("owner_setup_started_at", value)
        return parse_dt(value)

    def owner_setup_window_is_open(self, minutes: int = 30) -> bool:
        if self.owner_exists() or self.get_state("owner_setup_used") == "1":
            return False
        started_at = self.get_or_create_owner_setup_started_at()
        return now_utc() <= started_at + timedelta(minutes=minutes)

    def owner_setup_minutes_left(self, minutes: int = 30) -> int:
        started_at = self.get_or_create_owner_setup_started_at()
        expires_at = started_at + timedelta(minutes=minutes)
        left = int((expires_at - now_utc()).total_seconds() // 60)
        return max(0, left)

    def get_state(self, key: str) -> str | None:
        with self.database.connection() as conn:
            row = conn.execute("select value from app_state where key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.database.connection() as conn:
            conn.execute(
                "insert into app_state (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                (key, value),
            )
            conn.commit()

    def set_user_role(self, user_id: UUID, role: str) -> User:
        is_admin = 1 if role in {OWNER_ROLE, ADMIN_ROLE} else 0
        with self.database.connection() as conn:
            conn.execute("update users set role = ?, is_admin = ? where id = ?", (role, is_admin, str(user_id)))
            conn.commit()
        user = self.get_user_by_id(user_id)
        assert user is not None
        return user

    def create_admin_invite(self, created_by_user_id: UUID, token: str, hours: int = 24) -> None:
        invite_id = str(uuid4())
        expires_at = (now_utc() + timedelta(hours=hours)).isoformat()
        with self.database.connection() as conn:
            conn.execute(
                """
                insert into admin_invites (id, token_hash, role, created_by_user_id, expires_at, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (invite_id, token_hash(token), ADMIN_ROLE, str(created_by_user_id), expires_at, now_iso()),
            )
            conn.commit()

    def consume_admin_invite(self, token: str, user_id: UUID) -> tuple[bool, str]:
        with self.database.connection() as conn:
            row = conn.execute("select * from admin_invites where token_hash = ?", (token_hash(token),)).fetchone()
            if not row:
                return False, "Приглашение не найдено или уже недействительно."
            if row["used_at"]:
                return False, "Это приглашение уже использовано."
            if parse_dt(row["expires_at"]) < now_utc():
                return False, "Срок действия приглашения истёк."
            conn.execute(
                "update admin_invites set used_by_user_id = ?, used_at = ? where id = ?",
                (str(user_id), now_iso(), row["id"]),
            )
            conn.execute("update users set role = ?, is_admin = 1 where id = ?", (row["role"], str(user_id)))
            conn.commit()
        return True, "Доступ администратора выдан."


    def save_admin_session(self, telegram_id: int, chat_id: int, state: str | None, draft: dict, history: list[dict] | None = None) -> None:
        with self.database.connection() as conn:
            conn.execute(
                """
                insert into admin_sessions (telegram_id, chat_id, state, draft_json, history_json, updated_at)
                values (?, ?, ?, ?, ?, ?)
                on conflict(telegram_id) do update set
                    chat_id = excluded.chat_id,
                    state = excluded.state,
                    draft_json = excluded.draft_json,
                    history_json = excluded.history_json,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, chat_id, state, json.dumps(draft, ensure_ascii=False), json.dumps(history or [], ensure_ascii=False), now_iso()),
            )
            conn.commit()

    def load_admin_session(self, telegram_id: int) -> dict | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from admin_sessions where telegram_id = ?", (telegram_id,)).fetchone()
        if not row or not row["state"]:
            return None
        return {
            "telegram_id": row["telegram_id"],
            "chat_id": row["chat_id"],
            "state": row["state"],
            "draft": json.loads(row["draft_json"] or "{}"),
            "history": json.loads(row["history_json"] or "[]"),
            "updated_at": row["updated_at"],
        }

    def clear_admin_session(self, telegram_id: int) -> None:
        with self.database.connection() as conn:
            conn.execute("delete from admin_sessions where telegram_id = ?", (telegram_id,))
            conn.commit()

    def create_franchise(self, title: str, slug: str, description: str | None, created_by_user_id: UUID) -> Franchise:
        franchise_id = str(uuid4())
        with self.database.connection() as conn:
            conn.execute(
                "insert into restaurants (id, title, slug, description, created_by_user_id, created_at) values (?, ?, ?, ?, ?, ?)",
                (franchise_id, title, slug, description, str(created_by_user_id), now_iso()),
            )
            conn.commit()
        franchise = self.get_franchise_by_id(UUID(franchise_id))
        assert franchise is not None
        return franchise

    def list_franchises(self, include_inactive: bool = False) -> list[Franchise]:
        sql = "select * from restaurants"
        if not include_inactive:
            sql += " where is_active = 1"
        sql += " order by created_at desc"
        with self.database.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._franchise(row) for row in rows]

    def get_franchise_by_id(self, franchise_id: UUID) -> Franchise | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from restaurants where id = ?", (str(franchise_id),)).fetchone()
        return self._franchise(row) if row else None

    def get_franchise_by_slug(self, slug: str) -> Franchise | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from restaurants where lower(slug) = lower(?) and is_active = 1", (slug,)).fetchone()
        return self._franchise(row) if row else None

    def get_default_franchise(self) -> Franchise | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from restaurants where is_active = 1 order by created_at desc limit 1").fetchone()
        return self._franchise(row) if row else None

    def create_branch(self, franchise_id: UUID, title: str, address: str | None, phone: str | None) -> Branch:
        branch_id = str(uuid4())
        with self.database.connection() as conn:
            position = conn.execute("select coalesce(max(position), 0) + 1 as pos from branches where franchise_id = ?", (str(franchise_id),)).fetchone()["pos"]
            conn.execute(
                "insert into branches (id, franchise_id, title, address, phone, position, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                (branch_id, str(franchise_id), title, address, phone, position, now_iso()),
            )
            conn.commit()
        branch = self.get_branch(UUID(branch_id))
        assert branch is not None
        return branch

    def list_branches(self, franchise_id: UUID, include_inactive: bool = False) -> list[Branch]:
        sql = "select * from branches where franchise_id = ?"
        params: list[str] = [str(franchise_id)]
        if not include_inactive:
            sql += " and is_active = 1"
        sql += " order by position, created_at"
        with self.database.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._branch(row) for row in rows]

    def get_branch(self, branch_id: UUID) -> Branch | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from branches where id = ?", (str(branch_id),)).fetchone()
        return self._branch(row) if row else None

    def create_category(self, branch_id: UUID, title: str) -> Category:
        category_id = str(uuid4())
        with self.database.connection() as conn:
            position = conn.execute("select coalesce(max(position), 0) + 1 as pos from categories where branch_id = ?", (str(branch_id),)).fetchone()["pos"]
            conn.execute(
                "insert into categories (id, branch_id, title, position, created_at) values (?, ?, ?, ?, ?)",
                (category_id, str(branch_id), title, position, now_iso()),
            )
            conn.commit()
        category = self.get_category(UUID(category_id))
        assert category is not None
        return category

    def list_categories(self, branch_id: UUID, active_only: bool = True) -> list[Category]:
        sql = "select * from categories where branch_id = ?"
        if active_only:
            sql += " and is_active = 1"
        sql += " order by position, created_at"
        with self.database.connection() as conn:
            rows = conn.execute(sql, (str(branch_id),)).fetchall()
        return [self._category(row) for row in rows]

    def get_category(self, category_id: UUID) -> Category | None:
        with self.database.connection() as conn:
            row = conn.execute("select * from categories where id = ?", (str(category_id),)).fetchone()
        return self._category(row) if row else None

    def create_dish(self, branch_id: UUID, category_id: UUID, title: str, description: str | None, price: int | None, weight: str | None, photo_file_id: str | None) -> Dish:
        dish_id = str(uuid4())
        with self.database.connection() as conn:
            position = conn.execute("select coalesce(max(position), 0) + 1 as pos from dishes where category_id = ?", (str(category_id),)).fetchone()["pos"]
            conn.execute(
                """
                insert into dishes (id, branch_id, category_id, title, description, price, weight, photo_file_id, position, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (dish_id, str(branch_id), str(category_id), title, description, price, weight, photo_file_id, position, now_iso()),
            )
            conn.commit()
        dish = self.get_dish(UUID(dish_id))
        assert dish is not None
        return dish


    def update_dish(self, dish_id: UUID, category_id: UUID, title: str, description: str | None, price: int | None, weight: str | None, photo_file_id: str | None) -> Dish | None:
        with self.database.connection() as conn:
            conn.execute(
                """
                update dishes
                set category_id = ?, title = ?, description = ?, price = ?, weight = ?, photo_file_id = ?
                where id = ?
                """,
                (str(category_id), title, description, price, weight, photo_file_id, str(dish_id)),
            )
            conn.commit()
        return self.get_dish(dish_id)

    def list_dishes(self, branch_id: UUID, category_id: UUID | None = None, active_only: bool = True) -> list[Dish]:
        sql = """
        select d.*, c.title as category_title
        from dishes d
        join categories c on c.id = d.category_id
        where d.branch_id = ?
        """
        params: list[str] = [str(branch_id)]
        if category_id:
            sql += " and d.category_id = ?"
            params.append(str(category_id))
        if active_only:
            sql += " and d.is_active = 1 and c.is_active = 1"
        sql += " order by c.position, d.position, d.created_at"
        with self.database.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._dish(row) for row in rows]

    def get_dish(self, dish_id: UUID) -> Dish | None:
        with self.database.connection() as conn:
            row = conn.execute(
                "select d.*, c.title as category_title from dishes d join categories c on c.id = d.category_id where d.id = ?",
                (str(dish_id),),
            ).fetchone()
        return self._dish(row) if row else None

    def set_dish_active(self, dish_id: UUID, is_active: bool) -> None:
        with self.database.connection() as conn:
            conn.execute("update dishes set is_active = ? where id = ?", (1 if is_active else 0, str(dish_id)))
            conn.commit()

    def copy_menu(self, source_branch_id: UUID, target_branch_id: UUID) -> None:
        source_categories = self.list_categories(source_branch_id, active_only=False)
        with self.database.connection() as conn:
            conn.execute("delete from dishes where branch_id = ?", (str(target_branch_id),))
            conn.execute("delete from categories where branch_id = ?", (str(target_branch_id),))
            for category in source_categories:
                new_category_id = str(uuid4())
                conn.execute(
                    "insert into categories (id, branch_id, title, position, is_active, created_at) values (?, ?, ?, ?, ?, ?)",
                    (new_category_id, str(target_branch_id), category.title, category.position, 1 if category.is_active else 0, now_iso()),
                )
                dishes = conn.execute("select * from dishes where category_id = ? order by position, created_at", (str(category.id),)).fetchall()
                for dish in dishes:
                    conn.execute(
                        """
                        insert into dishes (id, branch_id, category_id, title, description, price, weight, photo_file_id, is_active, position, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()), str(target_branch_id), new_category_id, dish["title"], dish["description"], dish["price"],
                            dish["weight"], dish["photo_file_id"], dish["is_active"], dish["position"], now_iso(),
                        ),
                    )
            conn.commit()

    def _user(self, row) -> User:
        return User(UUID(row["id"]), row["telegram_id"], row["username"], row["first_name"], row["role"], bool(row["is_admin"]), parse_dt(row["created_at"]))

    def _franchise(self, row) -> Franchise:
        return Franchise(UUID(row["id"]), row["title"], row["slug"], row["description"], bool(row["is_active"]), UUID(row["created_by_user_id"]), parse_dt(row["created_at"]))

    def _branch(self, row) -> Branch:
        return Branch(UUID(row["id"]), UUID(row["franchise_id"]), row["title"], row["address"], row["phone"], bool(row["is_active"]), row["position"], parse_dt(row["created_at"]))

    def _category(self, row) -> Category:
        return Category(UUID(row["id"]), UUID(row["branch_id"]), row["title"], row["position"], bool(row["is_active"]), parse_dt(row["created_at"]))

    def _dish(self, row) -> Dish:
        return Dish(UUID(row["id"]), UUID(row["branch_id"]), UUID(row["category_id"]), row["category_title"], row["title"], row["description"], row["price"], row["weight"], row["photo_file_id"], bool(row["is_active"]), row["position"], parse_dt(row["created_at"]))
