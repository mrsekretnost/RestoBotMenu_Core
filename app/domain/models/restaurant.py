from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class User:
    id: UUID
    telegram_id: int
    username: str | None
    first_name: str | None
    role: str
    is_admin: bool
    created_at: datetime


@dataclass(slots=True)
class Franchise:
    id: UUID
    title: str
    slug: str
    description: str | None
    is_active: bool
    created_by_user_id: UUID
    created_at: datetime


@dataclass(slots=True)
class Branch:
    id: UUID
    franchise_id: UUID
    title: str
    address: str | None
    phone: str | None
    is_active: bool
    position: int
    created_at: datetime


@dataclass(slots=True)
class Category:
    id: UUID
    branch_id: UUID
    title: str
    position: int
    is_active: bool
    created_at: datetime


@dataclass(slots=True)
class Dish:
    id: UUID
    branch_id: UUID
    category_id: UUID
    category_title: str
    title: str
    description: str | None
    price: int | None
    weight: str | None
    photo_file_id: str | None
    is_active: bool
    position: int
    created_at: datetime
