from __future__ import annotations

import re
import secrets
from uuid import UUID

from app.application.dto import ActorCommand, CreateBranchCommand, CreateCategoryCommand, CreateDishCommand, CreateFranchiseCommand, PublicMenuCommand
from app.domain.models.restaurant import Branch, Category, Dish, Franchise, User
from app.infrastructure.db.repositories.restaurant_repository import ADMIN_ROLE, OWNER_ROLE, RestaurantRepository


class RestaurantService:
    OWNER_SETUP_MINUTES = 30

    def __init__(self, repository: RestaurantRepository) -> None:
        self.repository = repository

    def ensure_actor(self, command: ActorCommand) -> User:
        return self.repository.get_or_create_user(command.telegram_id, command.username, command.first_name)

    def is_admin(self, telegram_id: int, username: str | None = None, first_name: str | None = None) -> bool:
        user = self.repository.get_or_create_user(telegram_id, username, first_name)
        return user.role in {OWNER_ROLE, ADMIN_ROLE}

    def is_owner(self, telegram_id: int, username: str | None = None, first_name: str | None = None) -> bool:
        user = self.repository.get_or_create_user(telegram_id, username, first_name)
        return user.role == OWNER_ROLE

    def require_admin(self, command: ActorCommand) -> tuple[bool, str | None]:
        user = self.ensure_actor(command)
        if user.role not in {OWNER_ROLE, ADMIN_ROLE}:
            return False, "Этот раздел доступен только администратору."
        return True, None

    def require_owner(self, command: ActorCommand) -> tuple[bool, str | None, User | None]:
        user = self.ensure_actor(command)
        if user.role != OWNER_ROLE:
            return False, "Это действие доступно только владельцу.", user
        return True, None, user

    def owner_setup_status(self) -> tuple[bool, int, str | None]:
        if self.repository.owner_exists() or self.repository.get_state("owner_setup_used") == "1":
            return False, 0, "Владелец уже назначен."
        is_open = self.repository.owner_setup_window_is_open(self.OWNER_SETUP_MINUTES)
        minutes_left = self.repository.owner_setup_minutes_left(self.OWNER_SETUP_MINUTES)
        if not is_open:
            return False, 0, "Окно первичной настройки закрыто. Создайте новую базу данных или обратитесь к владельцу сервера."
        return True, minutes_left, None

    def claim_first_owner(self, command: ActorCommand) -> str:
        user = self.ensure_actor(command)
        is_open, _minutes_left, error = self.owner_setup_status()
        if not is_open:
            return error or "Назначение владельца недоступно."
        self.repository.set_user_role(user.id, OWNER_ROLE)
        self.repository.set_state("owner_setup_used", "1")
        return "Вы назначены владельцем. Теперь доступна админская панель."

    def create_admin_invite(self, command: ActorCommand, bot_username: str) -> tuple[str | None, str | None]:
        ok, error, owner = self.require_owner(command)
        if not ok or owner is None:
            return error or "Нет доступа.", None
        token = secrets.token_urlsafe(24)
        self.repository.create_admin_invite(owner.id, token, hours=24)
        link = f"https://t.me/{bot_username}?start=admin_invite_{token}"
        return None, link

    def claim_admin_invite(self, command: ActorCommand, token: str) -> str:
        user = self.ensure_actor(command)
        if user.role == OWNER_ROLE:
            return "Вы уже владелец. Приглашение не требуется."
        ok, message = self.repository.consume_admin_invite(token.strip(), user.id)
        return message if ok else message

    def create_franchise(self, command: CreateFranchiseCommand) -> tuple[str | None, Franchise | None]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, None
        title = command.title.strip()
        slug = self.normalize_slug(command.slug)
        if not title:
            return "Название франшизы не может быть пустым.", None
        if not slug:
            return "Код франшизы должен содержать латинские буквы или цифры.", None
        if self.repository.get_franchise_by_slug(slug):
            return "Такой код уже занят.", None
        user = self.ensure_actor(command)
        return None, self.repository.create_franchise(title, slug, self.clean_optional(command.description), user.id)

    def create_branch(self, command: CreateBranchCommand) -> tuple[str | None, Branch | None]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, None
        franchise = self.repository.get_franchise_by_id(command.franchise_id)
        if not franchise:
            return "Франшиза не найдена.", None
        title = command.title.strip()
        if not title:
            return "Название филиала не может быть пустым.", None
        return None, self.repository.create_branch(command.franchise_id, title, self.clean_optional(command.address), self.clean_optional(command.phone))

    def list_franchises_for_admin(self, command: ActorCommand) -> tuple[str | None, list[Franchise]]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, []
        return None, self.repository.list_franchises(include_inactive=True)

    def list_public_franchises(self) -> list[Franchise]:
        return self.repository.list_franchises(include_inactive=False)

    def get_public_franchise(self, command: PublicMenuCommand) -> tuple[str | None, Franchise | None]:
        if command.slug:
            slug = self.normalize_slug(command.slug)
            franchise = self.repository.get_franchise_by_slug(slug) if slug else None
        else:
            franchise = self.repository.get_default_franchise()
        if not franchise:
            return "Меню пока не создано.", None
        return None, franchise

    def create_category(self, command: CreateCategoryCommand) -> tuple[str | None, Category | None]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, None
        branch = self.repository.get_branch(command.branch_id)
        if not branch:
            return "Филиал не найден.", None
        title = command.title.strip()
        if not title:
            return "Название категории не может быть пустым.", None
        return None, self.repository.create_category(command.branch_id, title)

    def list_categories(self, branch_id: UUID, active_only: bool = True) -> list[Category]:
        return self.repository.list_categories(branch_id, active_only=active_only)

    def create_dish(self, command: CreateDishCommand) -> tuple[str | None, Dish | None]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, None
        branch = self.repository.get_branch(command.branch_id)
        category = self.repository.get_category(command.category_id)
        if not branch or not category or category.branch_id != command.branch_id:
            return "Филиал или категория не найдены.", None
        title = command.title.strip()
        if not title:
            return "Название блюда не может быть пустым.", None
        dish = self.repository.create_dish(
            branch_id=command.branch_id,
            category_id=command.category_id,
            title=title,
            description=self.clean_optional(command.description),
            price=command.price,
            weight=self.clean_optional(command.weight),
            photo_file_id=self.clean_optional(command.photo_file_id),
        )
        return None, dish


    def update_dish(self, command: CreateDishCommand, dish_id: UUID) -> tuple[str | None, Dish | None]:
        ok, error = self.require_admin(command)
        if not ok:
            return error, None
        dish = self.repository.get_dish(dish_id)
        branch = self.repository.get_branch(command.branch_id)
        category = self.repository.get_category(command.category_id)
        if not dish or not branch or not category or category.branch_id != command.branch_id:
            return "Блюдо, филиал или категория не найдены.", None
        title = command.title.strip()
        if not title:
            return "Название блюда не может быть пустым.", None
        updated = self.repository.update_dish(
            dish_id=dish_id,
            category_id=command.category_id,
            title=title,
            description=self.clean_optional(command.description),
            price=command.price,
            weight=self.clean_optional(command.weight),
            photo_file_id=self.clean_optional(command.photo_file_id),
        )
        return None, updated

    def list_public_menu(self, branch_id: UUID) -> tuple[list[Category], list[Dish]]:
        return self.repository.list_categories(branch_id, active_only=True), self.repository.list_dishes(branch_id, active_only=True)

    def list_branches(self, franchise_id: UUID, include_inactive: bool = False) -> list[Branch]:
        return self.repository.list_branches(franchise_id, include_inactive=include_inactive)

    def get_franchise(self, franchise_id: UUID) -> Franchise | None:
        return self.repository.get_franchise_by_id(franchise_id)

    def get_branch(self, branch_id: UUID) -> Branch | None:
        return self.repository.get_branch(branch_id)

    def get_dish(self, dish_id: UUID) -> Dish | None:
        return self.repository.get_dish(dish_id)

    def copy_menu_to_branch(self, command: ActorCommand, source_branch_id: UUID, target_branch_id: UUID) -> str:
        ok, error = self.require_admin(command)
        if not ok:
            return error or "Нет доступа."
        if source_branch_id == target_branch_id:
            return "Нельзя скопировать меню филиала в него же."
        source = self.repository.get_branch(source_branch_id)
        target = self.repository.get_branch(target_branch_id)
        if not source or not target or source.franchise_id != target.franchise_id:
            return "Филиалы не найдены или принадлежат разным франшизам."
        self.repository.copy_menu(source_branch_id, target_branch_id)
        return "Меню скопировано в выбранный филиал."

    def copy_menu_to_all_branches(self, command: ActorCommand, source_branch_id: UUID) -> str:
        ok, error = self.require_admin(command)
        if not ok:
            return error or "Нет доступа."
        source = self.repository.get_branch(source_branch_id)
        if not source:
            return "Филиал не найден."
        branches = self.repository.list_branches(source.franchise_id, include_inactive=True)
        copied = 0
        for branch in branches:
            if branch.id == source_branch_id:
                continue
            self.repository.copy_menu(source_branch_id, branch.id)
            copied += 1
        return f"Меню скопировано во все филиалы. Обновлено филиалов: {copied}."

    def set_dish_active(self, command: ActorCommand, dish_id: UUID, is_active: bool) -> str:
        ok, error = self.require_admin(command)
        if not ok:
            return error or "Нет доступа."
        self.repository.set_dish_active(dish_id, is_active)
        return "Статус блюда обновлён."

    @staticmethod
    def clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @staticmethod
    def normalize_slug(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9_]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value[:32]
