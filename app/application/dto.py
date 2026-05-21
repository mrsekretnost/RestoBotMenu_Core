from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class ActorCommand:
    telegram_id: int
    username: str | None
    first_name: str | None


@dataclass(slots=True)
class CreateFranchiseCommand(ActorCommand):
    title: str
    slug: str
    description: str | None = None


@dataclass(slots=True)
class CreateBranchCommand(ActorCommand):
    franchise_id: UUID
    title: str
    address: str | None = None
    phone: str | None = None


@dataclass(slots=True)
class CreateCategoryCommand(ActorCommand):
    branch_id: UUID
    title: str


@dataclass(slots=True)
class CreateDishCommand(ActorCommand):
    branch_id: UUID
    category_id: UUID
    title: str
    description: str | None
    price: int | None
    weight: str | None
    photo_file_id: str | None


@dataclass(slots=True)
class PublicMenuCommand:
    slug: str | None = None
