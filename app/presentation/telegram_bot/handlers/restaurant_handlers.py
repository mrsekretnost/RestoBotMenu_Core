from __future__ import annotations

from uuid import UUID

import telebot
from telebot import types

from app.application.dto import ActorCommand, CreateBranchCommand, CreateCategoryCommand, CreateDishCommand, CreateFranchiseCommand, PublicMenuCommand
from app.application.services.restaurant_service import RestaurantService
from app.domain.models.restaurant import Branch, Category, Dish, Franchise
from app.infrastructure.storage import PhotoStorage
from app.presentation.telegram_bot.keyboards.reply import BTN_ADMIN_PANEL, BTN_PUBLIC_MENU
from app.presentation.telegram_bot.message_utils import delete_user_message, get_last_bot_message_id, send_or_edit_message

_RUNTIME: dict[str, object] = {}
PUBLIC_DISHES_PER_PAGE = 6


UUID_DRAFT_KEYS = {"franchise_id", "branch_id", "category_id", "dish_id"}

STATE_PROMPTS = {
    "create_fr_title": "🏷 Название франшизы\n\nВведите общее название бренда, которое будут видеть гости. Например: «Coffee House»." ,
    "create_fr_slug": "🔗 Короткий код меню\n\nВведите код латиницей. Он нужен для ссылки на меню. Например: demo, coffee_house или central.",
    "create_fr_description": "📝 Описание франшизы\n\nДобавьте короткое описание бренда. Если описание не нужно, нажмите кнопку «Пропустить».",
    "branch_title": "📍 Название филиала\n\nВведите понятное название точки. Например: «Центр», «Астана», «Проспект Абая»." ,
    "branch_address": "🧭 Адрес филиала\n\nУкажите адрес, чтобы гостям было проще выбрать нужную точку. Если адрес пока не нужен, нажмите «Пропустить».",
    "branch_phone": "☎️ Телефон филиала\n\nУкажите контактный номер филиала. Если номер пока не нужен, нажмите «Пропустить».",
    "add_category": "🍽 Новая категория\n\nВведите название раздела меню. Например: «Завтраки», «Пицца», «Напитки»." ,
    "dish_title": "🍔 Название блюда\n\nВведите название так, как оно должно отображаться в меню.",
    "dish_description": "📝 Описание блюда\n\nОпишите состав, вкус или особенности подачи. Если описание не нужно, нажмите «Пропустить».",
    "dish_price": "💵 Цена\n\nВведите цену целым числом без валюты. Например: 2500. Если цену пока не нужно показывать, нажмите «Пропустить».",
    "dish_weight": "⚖️ Вес или объём\n\nНапример: 350 г, 0.3 л, 8 шт. Если указывать не нужно, нажмите «Пропустить».",
    "dish_photo": "📸 Фото блюда\n\nОтправьте фотографию блюда. Если фото пока нет, нажмите «Пропустить».",
    "dish_preview": "✅ Проверьте карточку блюда перед сохранением.",
    "edit_dish_title": "✏️ Новое название блюда\n\nВведите новое название блюда.",
    "edit_dish_description": "✏️ Новое описание\n\nОтправьте новое описание. Чтобы оставить текущее значение, нажмите «Пропустить».",
    "edit_dish_price": "✏️ Новая цена\n\nВведите цену целым числом без валюты. Чтобы оставить текущую цену, нажмите «Пропустить».",
    "edit_dish_weight": "✏️ Новый вес или объём\n\nНапример: 350 г, 0.3 л, 8 шт. Чтобы оставить текущее значение, нажмите «Пропустить».",
    "edit_dish_photo": "✏️ Новое фото\n\nОтправьте новую фотографию блюда. Чтобы оставить текущее фото, нажмите «Пропустить».",
}

SKIPPABLE_STATES = {
    "create_fr_description",
    "branch_address",
    "branch_phone",
    "dish_description",
    "dish_price",
    "dish_weight",
    "dish_photo",
    "edit_dish_description",
    "edit_dish_price",
    "edit_dish_weight",
    "edit_dish_photo",
}


def open_public_menu_from_start(bot: telebot.TeleBot, service: RestaurantService, chat_id: int, user_id: int) -> None:
    opener = _RUNTIME.get("open_public_menu")
    if callable(opener):
        opener(chat_id, user_id, None)
    else:
        send_or_edit_message(bot, chat_id, user_id, "Меню временно недоступно.")


def open_admin_from_start(bot: telebot.TeleBot, service: RestaurantService, chat_id: int, user_id: int, user) -> None:
    renderer = _RUNTIME.get("render")
    if callable(renderer):
        renderer(chat_id, user_id, {"view": "admin_home", "user": user})
    else:
        send_or_edit_message(bot, chat_id, user_id, "Админка временно недоступна.")


def register_restaurant_handlers(bot: telebot.TeleBot, service: RestaurantService, photo_storage: PhotoStorage) -> None:
    sessions: dict[tuple[int, int], dict] = {}
    bot_username_cache: dict[str, str] = {}

    def get_bot_username() -> str:
        if "value" not in bot_username_cache:
            bot_username_cache["value"] = bot.get_me().username
        return bot_username_cache["value"]

    def serialize_draft(draft: dict) -> dict:
        result = {}
        for key, value in draft.items():
            result[key] = str(value) if isinstance(value, UUID) else value
        return result

    def hydrate_draft(draft: dict) -> dict:
        result = dict(draft or {})
        for key in UUID_DRAFT_KEYS:
            if key in result and result[key] is not None and not isinstance(result[key], UUID):
                result[key] = UUID(str(result[key]))
        return result

    def serialize_history(history: list[dict]) -> list[dict]:
        return [{"state": item.get("state"), "draft": serialize_draft(item.get("draft", {}))} for item in history]

    def hydrate_history(history: list[dict]) -> list[dict]:
        return [{"state": item.get("state"), "draft": hydrate_draft(item.get("draft", {}))} for item in history or []]

    def get_session(chat_id: int, user_id: int) -> dict:
        session_key = (chat_id, user_id)
        if session_key in sessions:
            return sessions[session_key]
        saved = service.repository.load_admin_session(user_id)
        if saved:
            session = {
                "message_id": None,
                "state": saved["state"],
                "draft": hydrate_draft(saved["draft"]),
                "history": hydrate_history(saved.get("history", [])),
                "stack": [],
            }
        else:
            session = {"message_id": None, "state": None, "draft": {}, "history": [], "stack": []}
        sessions[session_key] = session
        return session

    def save_wizard(chat_id: int, user_id: int) -> None:
        session = get_session(chat_id, user_id)
        state = session.get("state")
        if not state:
            service.repository.clear_admin_session(user_id)
            return
        service.repository.save_admin_session(
            telegram_id=user_id,
            chat_id=chat_id,
            state=state,
            draft=serialize_draft(session.get("draft", {})),
            history=serialize_history(session.get("history", [])),
        )

    def clear_wizard(chat_id: int, user_id: int) -> None:
        session = get_session(chat_id, user_id)
        session["state"] = None
        session["draft"] = {}
        session["history"] = []
        service.repository.clear_admin_session(user_id)

    def actor(user) -> ActorCommand:
        return ActorCommand(telegram_id=user.id, username=user.username, first_name=user.first_name)

    def keyboard(buttons: list[tuple[str, str]], back: bool = True, admin_home: bool = False) -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup()
        for text, data in buttons:
            markup.row(types.InlineKeyboardButton(text=text, callback_data=data))
        navigation_row = []
        if back:
            navigation_row.append(types.InlineKeyboardButton(text="Назад", callback_data="nav:back"))
        if admin_home:
            navigation_row.append(types.InlineKeyboardButton(text="В главное меню", callback_data="adm:home"))
        if navigation_row:
            markup.row(*navigation_row)
        return markup

    def wizard_keyboard(chat_id: int, user_id: int) -> types.InlineKeyboardMarkup:
        session = get_session(chat_id, user_id)
        markup = types.InlineKeyboardMarkup()
        state = session.get("state")
        if state == "dish_preview":
            markup.row(types.InlineKeyboardButton(text="Сохранить блюдо", callback_data="wizard:save_dish"))
        elif state_has_saved_value(state, session.get("draft", {})):
            markup.row(types.InlineKeyboardButton(text="Далее", callback_data="wizard:next"))
        if state in SKIPPABLE_STATES:
            markup.row(types.InlineKeyboardButton(text="Пропустить", callback_data="wizard:skip"))
        row = []
        if session.get("history"):
            row.append(types.InlineKeyboardButton(text="Назад", callback_data="wizard:back"))
        row.append(types.InlineKeyboardButton(text="Отмена", callback_data="wizard:cancel"))
        markup.row(*row)
        markup.row(types.InlineKeyboardButton(text="В главное меню", callback_data="adm:home"))
        return markup

    def resume_keyboard() -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton(text="Продолжить заполнение", callback_data="wizard:resume"))
        markup.row(types.InlineKeyboardButton(text="Начать заново", callback_data="wizard:discard"))
        return markup

    def send_or_edit(chat_id: int, user_id: int, text: str, markup: types.InlineKeyboardMarkup | None = None, photo=None) -> None:
        session = get_session(chat_id, user_id)
        send_or_edit_message(bot, chat_id, user_id, text, reply_markup=markup, photo=photo)
        session["message_id"] = get_last_bot_message_id(chat_id, user_id)

    def format_saved_value(value) -> str:
        if value is None or value == "":
            return "пока не указано"
        return str(value)

    def state_has_saved_value(state: str | None, draft: dict) -> bool:
        if not state:
            return False
        value_keys = {
            "create_fr_title": "title",
            "create_fr_slug": "slug",
            "create_fr_description": "description",
            "branch_title": "title",
            "branch_address": "address",
            "branch_phone": "phone",
            "add_category": "title",
            "dish_title": "title",
            "dish_description": "description",
            "dish_price": "price",
            "dish_weight": "weight",
            "dish_photo": "photo_object_key",
        }
        if state in value_keys:
            key = value_keys[state]
            return key in draft and draft.get(key) not in ("",)
        if state.startswith("edit_dish_"):
            return "current_value" in draft
        return False

    def prompt_for_state(state: str | None, draft: dict) -> str:
        if not state:
            return "Продолжите заполнение."
        base = STATE_PROMPTS.get(state, "Продолжите заполнение.")
        saved_map = {
            "create_fr_title": ("Название", draft.get("title")),
            "create_fr_slug": ("Код", draft.get("slug")),
            "create_fr_description": ("Описание", draft.get("description")),
            "branch_title": ("Название филиала", draft.get("title")),
            "branch_address": ("Адрес", draft.get("address")),
            "branch_phone": ("Телефон", draft.get("phone")),
            "dish_title": ("Название блюда", draft.get("title")),
            "dish_description": ("Описание", draft.get("description")),
            "dish_price": ("Цена", draft.get("price")),
            "dish_weight": ("Вес или объём", draft.get("weight")),
            "dish_photo": ("Фото", "добавлено" if draft.get("photo_object_key") else None),
            "dish_preview": ("Карточка", "готова к проверке"),
        }
        if state in saved_map:
            label, value = saved_map[state]
            return f"{base}\n\nСохранённое значение: {label}: {format_saved_value(value)}"
        if state.startswith("edit_dish_") and "current_value" in draft:
            return f"{base}\n\nТекущее значение: {format_saved_value(draft.get('current_value'))}"
        return base

    def render_dish_preview_text(draft: dict) -> str:
        lines = ["👀 Предпросмотр карточки блюда", "", f"🍴 {draft.get('title') or 'Без названия'}"]
        if draft.get("price") is not None:
            lines.append(f"Цена: {draft.get('price')} ₽")
        if draft.get("weight"):
            lines.append(f"Вес или объём: {draft.get('weight')}")
        if draft.get("description"):
            lines.extend(["", str(draft.get("description"))])
        if not draft.get("photo_object_key"):
            lines.extend(["", "Фото не добавлено."])
        lines.extend(["", "Если всё верно, нажмите «Сохранить блюдо». Чтобы изменить данные, нажмите «Назад»."])
        return "\n".join(lines).strip()

    def show_current_wizard_step(chat_id: int, user_id: int) -> None:
        session = get_session(chat_id, user_id)
        state = session.get("state")
        draft = session.get("draft", {})
        if state == "dish_preview":
            send_or_edit(chat_id, user_id, render_dish_preview_text(draft), wizard_keyboard(chat_id, user_id), photo_storage.get_photo_source(draft.get("photo_object_key")))
            return
        send_or_edit(chat_id, user_id, prompt_for_state(state, draft), wizard_keyboard(chat_id, user_id))

    def start_wizard(chat_id: int, user_id: int, state: str, draft: dict) -> None:
        session = get_session(chat_id, user_id)
        session["state"] = state
        session["draft"] = draft
        session["history"] = []
        save_wizard(chat_id, user_id)
        send_or_edit(chat_id, user_id, prompt_for_state(state, draft), wizard_keyboard(chat_id, user_id))

    def go_to_step(chat_id: int, user_id: int, state: str, draft: dict) -> None:
        session = get_session(chat_id, user_id)
        session["history"].append({"state": session.get("state"), "draft": dict(session.get("draft", {}))})
        session["state"] = state
        session["draft"] = draft
        save_wizard(chat_id, user_id)
        send_or_edit(chat_id, user_id, prompt_for_state(state, draft), wizard_keyboard(chat_id, user_id))

    def advance_with_saved_value(chat_id: int, user, state: str | None, draft: dict) -> None:
        if not state or not state_has_saved_value(state, draft):
            show_current_wizard_step(chat_id, user.id)
            return
        if state == "create_fr_title":
            go_to_step(chat_id, user.id, "create_fr_slug", draft)
            return
        if state == "create_fr_slug":
            go_to_step(chat_id, user.id, "create_fr_description", draft)
            return
        if state == "create_fr_description":
            error, franchise = service.create_franchise(CreateFranchiseCommand(
                telegram_id=user.id, username=user.username, first_name=user.first_name,
                title=draft.get("title", ""), slug=draft.get("slug", ""), description=draft.get("description"),
            ))
            clear_wizard(chat_id, user.id)
            render(chat_id, user.id, {"view": "franchise", "franchise_id": franchise.id}) if franchise and not error else send_or_edit(chat_id, user.id, error or "Не удалось создать франшизу.", keyboard([], back=True))
            return
        if state == "branch_title":
            go_to_step(chat_id, user.id, "branch_address", draft)
            return
        if state == "branch_address":
            go_to_step(chat_id, user.id, "branch_phone", draft)
            return
        if state == "branch_phone":
            error, branch = service.create_branch(CreateBranchCommand(
                telegram_id=user.id, username=user.username, first_name=user.first_name,
                franchise_id=draft["franchise_id"], title=draft.get("title", ""), address=draft.get("address"), phone=draft.get("phone"),
            ))
            clear_wizard(chat_id, user.id)
            render(chat_id, user.id, {"view": "branch", "branch_id": branch.id}) if branch and not error else send_or_edit(chat_id, user.id, error or "Не удалось создать филиал.", keyboard([], back=True))
            return
        if state == "add_category":
            error, category = service.create_category(CreateCategoryCommand(
                telegram_id=user.id, username=user.username, first_name=user.first_name,
                branch_id=draft["branch_id"], title=draft.get("title", ""),
            ))
            branch_id = draft["branch_id"]
            clear_wizard(chat_id, user.id)
            render(chat_id, user.id, {"view": "categories", "branch_id": branch_id}) if not error else send_or_edit(chat_id, user.id, error, keyboard([], back=True))
            return
        if state == "dish_title":
            go_to_step(chat_id, user.id, "dish_description", draft)
            return
        if state == "dish_description":
            go_to_step(chat_id, user.id, "dish_price", draft)
            return
        if state == "dish_price":
            go_to_step(chat_id, user.id, "dish_weight", draft)
            return
        if state == "dish_weight":
            go_to_step(chat_id, user.id, "dish_photo", draft)
            return
        if state == "dish_photo":
            go_to_step(chat_id, user.id, "dish_preview", draft)
            return
        if state.startswith("edit_dish_"):
            field = state.replace("edit_dish_", "")
            apply_dish_edit(chat_id, user, draft, field, None, skipped=True)
            return
        show_current_wizard_step(chat_id, user.id)

    def render(chat_id: int, user_id: int, screen: dict, push: bool = False) -> None:
        clear_wizard(chat_id, user_id)
        session = get_session(chat_id, user_id)
        if push:
            session["stack"].append(screen)
        else:
            if not session["stack"]:
                session["stack"].append(screen)
            else:
                session["stack"][-1] = screen

        view = screen.get("view")
        text = "Экран не найден."
        buttons: list[tuple[str, str]] = []
        photo = None
        back = True

        if view == "admin_home":
            error, franchises = service.list_franchises_for_admin(actor(screen["user"]))
            if error:
                send_or_edit(chat_id, user_id, error, None)
                return
            is_owner = service.is_owner(screen["user"].id, screen["user"].username, screen["user"].first_name)
            back = False
            text = "⚙️ Панель управления\n\nЗдесь можно управлять франшизами, филиалами и меню. Выберите нужную франшизу или создайте новую."
            buttons = [(item.title, f"adm:fr:{item.id}") for item in franchises]
            buttons.append(("Создать франшизу", "adm:create_fr"))
            if is_owner:
                buttons.append(("Пригласить администратора", "adm:create_admin_invite"))

        elif view == "franchise":
            franchise = service.get_franchise(screen["franchise_id"])
            if not franchise:
                text = "Франшиза не найдена."
            else:
                branches = service.list_branches(franchise.id, include_inactive=True)
                text = (
                    f"🏷 {franchise.title}\n\n"
                    f"Код меню: {franchise.slug}\n"
                    f"Описание: {franchise.description or 'не указано'}\n\n"
                    f"Филиалов: {len(branches)}\n\n"
                    "Выберите филиал для редактирования или добавьте новую точку."
                )
                buttons = [(branch.title, f"adm:br:{branch.id}") for branch in branches]
                buttons.append(("Добавить филиал", f"adm:addbr:{franchise.id}"))
                buttons.append(("Посмотреть публично", f"pub:fr:{franchise.id}"))

        elif view == "branch":
            branch = service.get_branch(screen["branch_id"])
            if not branch:
                text = "Филиал не найден."
            else:
                categories = service.list_categories(branch.id, active_only=False)
                dishes = service.repository.list_dishes(branch.id, active_only=False)
                text = (
                    f"📍 Филиал: {branch.title}\n\n"
                    f"Адрес: {branch.address or 'не указан'}\n"
                    f"Телефон: {branch.phone or 'не указан'}\n\n"
                    f"Категорий: {len(categories)}\n"
                    f"Блюд: {len(dishes)}\n\n"
                    "Здесь редактируется меню именно этого филиала."
                )
                buttons = [
                    ("Категории", f"adm:cats:{branch.id}"),
                    ("Добавить категорию", f"adm:addcat:{branch.id}"),
                    ("Добавить блюдо", f"adm:adddish:{branch.id}"),
                    ("Скопировать меню отсюда", f"adm:copy_from:{branch.id}"),
                    ("Посмотреть публично", f"pub:branch:{branch.id}"),
                ]

        elif view == "categories":
            branch = service.get_branch(screen["branch_id"])
            categories = service.list_categories(screen["branch_id"], active_only=False)
            text = f"🍽 Категории филиала {branch.title if branch else ''}\n\nВыберите категорию или добавьте новый раздел меню."
            buttons = [(item.title, f"adm:cat:{item.id}") for item in categories]
            buttons.append(("Добавить категорию", f"adm:addcat:{screen['branch_id']}"))

        elif view == "category":
            branch_id = screen["branch_id"]
            category_id = screen["category_id"]
            category = service.repository.get_category(category_id)
            dishes = service.repository.list_dishes(branch_id, category_id, active_only=False)
            text = f"🍴 Категория: {category.title if category else ''}\n\nВыберите блюдо для просмотра или редактирования."
            buttons = [(dish.title, f"adm:dish:{dish.id}") for dish in dishes]
            buttons.append(("Добавить блюдо", f"adm:adddishcat:{category_id}"))

        elif view == "copy_targets":
            source_branch = service.get_branch(screen["source_branch_id"])
            branches = service.list_branches(source_branch.franchise_id, include_inactive=True) if source_branch else []
            text = "📋 Копирование меню\n\nВыберите филиал, куда нужно перенести меню. Текущее меню выбранного филиала будет полностью заменено."
            buttons = [(branch.title, f"adm:copy_to:{branch.id}") for branch in branches if branch.id != screen["source_branch_id"]]
            buttons.append(("Скопировать во все филиалы", "adm:copy_all"))

        elif view == "public_franchise":
            franchise = screen["franchise"]
            branches = service.list_branches(franchise.id, include_inactive=False)
            text = render_public_franchise(franchise, branches)
            buttons = [(branch.title, f"pub:branch:{branch.id}") for branch in branches]
            back = False

        elif view == "public_franchise_select":
            franchises = service.list_public_franchises()
            text = "🏷 Выберите ресторан\n\nНиже показаны доступные франшизы."
            buttons = [(franchise.title, f"pub:fr:{franchise.id}") for franchise in franchises]
            back = False

        elif view == "public_branch":
            branch = service.get_branch(screen["branch_id"])
            if not branch:
                text = "Филиал не найден."
            else:
                franchise = service.get_franchise(branch.franchise_id)
                categories, dishes = service.list_public_menu(branch.id)
                text = render_public_branch(franchise, branch, categories, dishes)
                buttons = [(category.title, f"pub:cat:{category.id}") for category in categories]

        elif view == "public_category":
            branch = service.get_branch(screen["branch_id"])
            category = service.repository.get_category(screen["category_id"])
            dishes = service.repository.list_dishes(screen["branch_id"], screen["category_id"], active_only=True)
            page = int(screen.get("page", 0))
            total_pages = max(1, (len(dishes) + PUBLIC_DISHES_PER_PAGE - 1) // PUBLIC_DISHES_PER_PAGE)
            page = max(0, min(page, total_pages - 1))
            start = page * PUBLIC_DISHES_PER_PAGE
            page_dishes = dishes[start:start + PUBLIC_DISHES_PER_PAGE]
            text = render_public_category(branch, category, dishes, page, total_pages)
            buttons = [(dish_button_title(dish), f"pub:dish:{dish.id}") for dish in page_dishes]
            page_row = []
            if page > 0:
                page_row.append(("◀️ Назад", f"pub:catp:{category.id}:{page - 1}"))
            if page < total_pages - 1:
                page_row.append(("Вперёд ▶️", f"pub:catp:{category.id}:{page + 1}"))
            buttons.extend(page_row)

        elif view == "public_dish":
            dish = service.get_dish(screen["dish_id"])
            if not dish:
                text = "Блюдо не найдено."
            else:
                text = render_dish_text(dish)
                photo = photo_storage.get_photo_source(dish.photo_file_id)
                buttons = []

        elif view == "dish":
            dish = service.get_dish(screen["dish_id"])
            if not dish:
                text = "Блюдо не найдено."
            else:
                text = render_admin_dish_text(dish)
                photo = photo_storage.get_photo_source(dish.photo_file_id)
                buttons = [
                    ("Изменить название", f"adm:editdish:title:{dish.id}"),
                    ("Изменить описание", f"adm:editdish:description:{dish.id}"),
                    ("Изменить цену", f"adm:editdish:price:{dish.id}"),
                    ("Изменить вес", f"adm:editdish:weight:{dish.id}"),
                    ("Изменить фото", f"adm:editdish:photo:{dish.id}"),
                    ("Скрыть блюдо" if dish.is_active else "Показать блюдо", f"adm:toggledish:{dish.id}"),
                ]

        send_or_edit(chat_id, user_id, text, keyboard(buttons, back=back, admin_home=str(view).startswith(("admin", "franchise", "branch", "categor", "copy_", "dish"))) if buttons or back or str(view).startswith(("admin", "franchise", "branch", "categor", "copy_", "dish")) else None, photo=photo)

    def render_public_franchise(franchise: Franchise, branches: list[Branch]) -> str:
        lines = [f"🏷 {franchise.title}"]
        if franchise.description:
            lines.extend(["", franchise.description])
        lines.append("")
        if not branches:
            lines.append("Филиалы пока не добавлены. Меню появится здесь после настройки.")
        else:
            lines.append("Выберите филиал, чтобы открыть его меню.")
        return "\n".join(lines).strip()

    def render_public_branch(franchise: Franchise | None, branch: Branch, categories: list[Category], dishes: list[Dish]) -> str:
        lines = [f"🏷 {franchise.title if franchise else 'Меню'}", f"📍 {branch.title}"]
        if branch.address:
            lines.append(f"Адрес: {branch.address}")
        if branch.phone:
            lines.append(f"Телефон: {branch.phone}")
        lines.append("")
        if not categories:
            lines.append("Меню этого филиала пока пустое.")
        else:
            lines.append("Выберите раздел меню.")
            lines.append(f"Разделов: {len(categories)}")
            lines.append(f"Блюд: {len(dishes)}")
        return "\n".join(lines).strip()

    def render_public_category(branch: Branch | None, category: Category | None, dishes: list[Dish], page: int = 0, total_pages: int = 1) -> str:
        lines = [f"📍 {branch.title}" if branch else "Меню", f"🍽 {category.title if category else 'Категория'}"]
        if not dishes:
            lines.extend(["", "В этом разделе пока нет блюд."])
        else:
            lines.extend(["", "Выберите блюдо кнопкой ниже, чтобы посмотреть состав, цену и фото."])
            if total_pages > 1:
                lines.append(f"Страница {page + 1} из {total_pages}")
        return "\n".join(lines).strip()

    def dish_button_title(dish: Dish) -> str:
        parts = [dish.title]
        if dish.price is not None:
            parts.append(f"{dish.price} ₽")
        if dish.weight:
            parts.append(dish.weight)
        return " · ".join(parts)

    def render_dish_text(dish: Dish) -> str:
        lines = [f"🍴 {dish.title}"]
        if dish.price is not None:
            lines.append(f"Цена: {dish.price} ₽")
        if dish.weight:
            lines.append(f"Вес или объём: {dish.weight}")
        if dish.description:
            lines.extend(["", dish.description])
        return "\n".join(lines).strip()

    def render_admin_dish_text(dish: Dish) -> str:
        status = "показывается гостям" if dish.is_active else "скрыто из публичного меню"
        lines = [f"🍴 {dish.title}", f"Категория: {dish.category_title}", f"Статус: {status}"]
        if dish.price is not None:
            lines.append(f"Цена: {dish.price} ₽")
        if dish.weight:
            lines.append(f"Вес или объём: {dish.weight}")
        if dish.description:
            lines.extend(["", dish.description])
        lines.extend(["", "Выберите, что нужно изменить."])
        return "\n".join(lines).strip()

    def open_public_menu(chat_id: int, user_id: int, slug: str | None = None) -> None:
        if not slug:
            franchises = service.list_public_franchises()
            if len(franchises) == 1:
                render(chat_id, user_id, {"view": "public_franchise", "franchise": franchises[0]})
            elif len(franchises) > 1:
                render(chat_id, user_id, {"view": "public_franchise_select"})
            else:
                send_or_edit(chat_id, user_id, "Меню пока не создано.")
            return
        error, franchise = service.get_public_franchise(PublicMenuCommand(slug=slug))
        if error or not franchise:
            send_or_edit(chat_id, user_id, error or "Меню не найдено.")
            return
        render(chat_id, user_id, {"view": "public_franchise", "franchise": franchise})

    def finish_dish_creation(chat_id: int, user, draft: dict, photo_object_key: str | None = None) -> None:
        photo_key = photo_object_key if photo_object_key is not None else draft.get("photo_object_key")
        error, dish = service.create_dish(CreateDishCommand(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            branch_id=draft["branch_id"],
            category_id=draft["category_id"],
            title=draft.get("title", ""),
            description=draft.get("description"),
            price=draft.get("price"),
            weight=draft.get("weight"),
            photo_file_id=photo_key,
        ))
        clear_wizard(chat_id, user.id)
        if error or not dish:
            send_or_edit(chat_id, user.id, error or "Не удалось добавить блюдо.", keyboard([], back=True))
        else:
            send_or_edit(chat_id, user.id, "✅ Блюдо добавлено в меню.\n\nТеперь его можно открыть в филиале, проверить описание и при необходимости отредактировать.", keyboard([], back=True))

    def apply_dish_edit(chat_id: int, user, draft: dict, field: str, value, skipped: bool = False) -> None:
        dish = service.get_dish(draft["dish_id"])
        if not dish:
            clear_wizard(chat_id, user.id)
            send_or_edit(chat_id, user.id, "Блюдо не найдено.", keyboard([], back=True))
            return

        title = dish.title
        description = dish.description
        price = dish.price
        weight = dish.weight
        photo_file_id = dish.photo_file_id

        if not skipped:
            if field == "title":
                title = str(value).strip()
            elif field == "description":
                description = str(value).strip() or None
            elif field == "price":
                price = int(value) if str(value).isdigit() else None
            elif field == "weight":
                weight = str(value).strip() or None
            elif field == "photo":
                photo_file_id = value

        error, updated = service.update_dish(CreateDishCommand(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            branch_id=dish.branch_id,
            category_id=dish.category_id,
            title=title,
            description=description,
            price=price,
            weight=weight,
            photo_file_id=photo_file_id,
        ), dish.id)
        clear_wizard(chat_id, user.id)
        if error or not updated:
            send_or_edit(chat_id, user.id, error or "Не удалось обновить блюдо.", keyboard([], back=True))
        else:
            render(chat_id, user.id, {"view": "dish", "dish_id": updated.id})

    def offer_resume_or_admin(chat_id: int, user_id: int, user) -> None:
        session = get_session(chat_id, user_id)
        if session.get("state"):
            send_or_edit(
                chat_id,
                user_id,
                "↩️ Найден незавершённый черновик.\n\nМожно продолжить с того же шага или начать заполнение заново.",
                resume_keyboard(),
            )
            return
        render(chat_id, user_id, {"view": "admin_home", "user": user})

    _RUNTIME["render"] = render
    _RUNTIME["open_public_menu"] = open_public_menu

    @bot.message_handler(commands=["admin"])
    def handle_admin(message: telebot.types.Message) -> None:
        offer_resume_or_admin(message.chat.id, message.from_user.id, message.from_user)
        delete_user_message(bot, message)

    @bot.message_handler(func=lambda message: message.text == BTN_ADMIN_PANEL)
    def handle_admin_button(message: telebot.types.Message) -> None:
        handle_admin(message)

    @bot.message_handler(commands=["menu"])
    def handle_menu(message: telebot.types.Message) -> None:
        parts = message.text.split(maxsplit=1) if message.text else []
        slug = parts[1].strip() if len(parts) > 1 else None
        open_public_menu(message.chat.id, message.from_user.id, slug)
        delete_user_message(bot, message)

    @bot.message_handler(func=lambda message: message.text == BTN_PUBLIC_MENU)
    def handle_public_button(message: telebot.types.Message) -> None:
        open_public_menu(message.chat.id, message.from_user.id)
        delete_user_message(bot, message)

    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call: telebot.types.CallbackQuery) -> None:
        data = call.data or ""
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        session = get_session(chat_id, user_id)
        bot.answer_callback_query(call.id)

        if data == "wizard:resume":
            state = session.get("state")
            if state:
                show_current_wizard_step(chat_id, user_id)
            else:
                render(chat_id, user_id, {"view": "admin_home", "user": call.from_user})
            return
        if data == "wizard:discard":
            clear_wizard(chat_id, user_id)
            render(chat_id, user_id, {"view": "admin_home", "user": call.from_user})
            return
        if data == "wizard:cancel":
            clear_wizard(chat_id, user_id)
            send_or_edit(chat_id, user_id, "Заполнение отменено.", keyboard([], back=True, admin_home=True))
            return
        if data == "wizard:next":
            advance_with_saved_value(chat_id, call.from_user, session.get("state"), session.get("draft", {}))
            return
        if data == "wizard:skip":
            state = session.get("state")
            draft = session.get("draft", {})
            if state == "create_fr_description":
                draft["description"] = None
                error, franchise = service.create_franchise(CreateFranchiseCommand(
                    telegram_id=call.from_user.id, username=call.from_user.username, first_name=call.from_user.first_name,
                    title=draft.get("title", ""), slug=draft.get("slug", ""), description=None,
                ))
                clear_wizard(chat_id, user_id)
                render(chat_id, user_id, {"view": "franchise", "franchise_id": franchise.id}) if franchise and not error else send_or_edit(chat_id, user_id, error or "Не удалось создать франшизу.", keyboard([], back=True))
                return
            if state == "branch_address":
                draft["address"] = None
                go_to_step(chat_id, user_id, "branch_phone", draft)
                return
            if state == "branch_phone":
                draft["phone"] = None
                error, branch = service.create_branch(CreateBranchCommand(
                    telegram_id=call.from_user.id, username=call.from_user.username, first_name=call.from_user.first_name,
                    franchise_id=draft["franchise_id"], title=draft.get("title", ""), address=draft.get("address"), phone=None,
                ))
                clear_wizard(chat_id, user_id)
                render(chat_id, user_id, {"view": "branch", "branch_id": branch.id}) if branch and not error else send_or_edit(chat_id, user_id, error or "Не удалось создать филиал.", keyboard([], back=True))
                return
            if state == "dish_description":
                draft["description"] = None
                go_to_step(chat_id, user_id, "dish_price", draft)
                return
            if state == "dish_price":
                draft["price"] = None
                go_to_step(chat_id, user_id, "dish_weight", draft)
                return
            if state == "dish_weight":
                draft["weight"] = None
                go_to_step(chat_id, user_id, "dish_photo", draft)
                return
            if state == "dish_photo":
                draft["photo_object_key"] = None
                go_to_step(chat_id, user_id, "dish_preview", draft)
                return
            if state and state.startswith("edit_dish_"):
                field = state.replace("edit_dish_", "")
                apply_dish_edit(chat_id, call.from_user, draft, field, None, skipped=True)
                return
        if data == "wizard:save_dish":
            draft = session.get("draft", {})
            finish_dish_creation(chat_id, call.from_user, draft)
            return
        if data == "wizard:back":
            history = session.get("history", [])
            if history:
                previous = history.pop()
                session["state"] = previous.get("state")
                session["draft"] = previous.get("draft", {})
                save_wizard(chat_id, user_id)
            state = session.get("state")
            show_current_wizard_step(chat_id, user_id)
            return

        if data == "nav:back":
            if len(session["stack"]) > 1:
                session["stack"].pop()
            if session["stack"]:
                render(chat_id, user_id, session["stack"][-1])
            return
        if data == "adm:home":
            clear_wizard(chat_id, user_id)
            render(chat_id, user_id, {"view": "admin_home", "user": call.from_user})
            return
        if data == "adm:create_admin_invite":
            error, link = service.create_admin_invite(actor(call.from_user), get_bot_username())
            if error or not link:
                send_or_edit(chat_id, user_id, error or "Не удалось создать приглашение.", keyboard([], back=True))
            else:
                text = "Одноразовая ссылка для администратора создана.\n\n" + link + "\n\nСсылка действует 24 часа и станет недействительной после первого использования."
                send_or_edit(chat_id, user_id, text, keyboard([], back=True))
            return
        if data == "adm:create_fr":
            start_wizard(chat_id, user_id, "create_fr_title", {})
            return
        if data.startswith("adm:fr:"):
            render(chat_id, user_id, {"view": "franchise", "franchise_id": UUID(data.split(":")[2])}, push=True)
            return
        if data.startswith("adm:addbr:"):
            start_wizard(chat_id, user_id, "branch_title", {"franchise_id": UUID(data.split(":")[2])})
            return
        if data.startswith("adm:br:"):
            render(chat_id, user_id, {"view": "branch", "branch_id": UUID(data.split(":")[2])}, push=True)
            return
        if data.startswith("adm:cats:"):
            render(chat_id, user_id, {"view": "categories", "branch_id": UUID(data.split(":")[2])}, push=True)
            return
        if data.startswith("adm:addcat:"):
            start_wizard(chat_id, user_id, "add_category", {"branch_id": UUID(data.split(":")[2])})
            return
        if data.startswith("adm:cat:"):
            category = service.repository.get_category(UUID(data.split(":")[2]))
            if category:
                render(chat_id, user_id, {"view": "category", "branch_id": category.branch_id, "category_id": category.id}, push=True)
            return
        if data.startswith("adm:adddishcat:"):
            category = service.repository.get_category(UUID(data.split(":")[2]))
            if not category:
                send_or_edit(chat_id, user_id, "Категория не найдена.", keyboard([], back=True))
                return
            start_wizard(chat_id, user_id, "dish_title", {"branch_id": category.branch_id, "category_id": category.id})
            return
        if data.startswith("adm:adddish:"):
            branch_id = UUID(data.split(":")[2])
            categories = service.list_categories(branch_id, active_only=True)
            if not categories:
                send_or_edit(chat_id, user_id, "Сначала добавьте хотя бы одну категорию.", keyboard([], back=True))
                return
            buttons = [(category.title, f"adm:adddishcat:{category.id}") for category in categories]
            send_or_edit(chat_id, user_id, "Выберите категорию для нового блюда.", keyboard(buttons, back=True))
            return
        if data.startswith("adm:dish:"):
            dish = service.get_dish(UUID(data.split(":")[2]))
            if dish:
                render(chat_id, user_id, {"view": "dish", "dish_id": dish.id}, push=True)
            return
        if data.startswith("adm:editdish:"):
            parts = data.split(":")
            field = parts[2]
            dish = service.get_dish(UUID(parts[3]))
            if not dish:
                send_or_edit(chat_id, user_id, "Блюдо не найдено.", keyboard([], back=True, admin_home=True))
                return
            current_values = {
                "title": dish.title,
                "description": dish.description,
                "price": dish.price,
                "weight": dish.weight,
                "photo": "фото уже добавлено" if dish.photo_file_id else None,
            }
            start_wizard(chat_id, user_id, f"edit_dish_{field}", {"dish_id": dish.id, "current_value": current_values.get(field)})
            return
        if data.startswith("adm:toggledish:"):
            dish = service.get_dish(UUID(data.split(":")[2]))
            if not dish:
                send_or_edit(chat_id, user_id, "Блюдо не найдено.", keyboard([], back=True))
                return
            service.set_dish_active(actor(call.from_user), dish.id, not dish.is_active)
            render(chat_id, user_id, {"view": "dish", "dish_id": dish.id})
            return
        if data.startswith("adm:copy_from:"):
            render(chat_id, user_id, {"view": "copy_targets", "source_branch_id": UUID(data.split(":")[2])}, push=True)
            return
        if data.startswith("adm:copy_to:"):
            current = session["stack"][-1] if session.get("stack") else {}
            source_id = current.get("source_branch_id")
            target_id = UUID(data.split(":")[2])
            if not source_id:
                send_or_edit(chat_id, user_id, "Не найден исходный филиал для копирования.", keyboard([], back=True))
                return
            result = service.copy_menu_to_branch(actor(call.from_user), source_id, target_id)
            send_or_edit(chat_id, user_id, result, keyboard([], back=True))
            return
        if data == "adm:copy_all":
            current = session["stack"][-1] if session.get("stack") else {}
            source_id = current.get("source_branch_id")
            if not source_id:
                send_or_edit(chat_id, user_id, "Не найден исходный филиал для копирования.", keyboard([], back=True))
                return
            result = service.copy_menu_to_all_branches(actor(call.from_user), source_id)
            send_or_edit(chat_id, user_id, result, keyboard([], back=True))
            return
        if data.startswith("pub:fr:"):
            franchise = service.get_franchise(UUID(data.split(":")[2]))
            if franchise:
                render(chat_id, user_id, {"view": "public_franchise", "franchise": franchise}, push=True)
            return
        if data.startswith("pub:branch:"):
            render(chat_id, user_id, {"view": "public_branch", "branch_id": UUID(data.split(":")[2])}, push=True)
            return
        if data.startswith("pub:cat:"):
            category = service.repository.get_category(UUID(data.split(":")[2]))
            if not category:
                send_or_edit(chat_id, user_id, "Категория не найдена.", keyboard([], back=True))
                return
            render(chat_id, user_id, {"view": "public_category", "branch_id": category.branch_id, "category_id": category.id}, push=True)
            return
        if data.startswith("pub:catp:"):
            parts = data.split(":")
            category = service.repository.get_category(UUID(parts[2]))
            if not category:
                send_or_edit(chat_id, user_id, "Категория не найдена.", keyboard([], back=True))
                return
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            render(chat_id, user_id, {"view": "public_category", "branch_id": category.branch_id, "category_id": category.id, "page": page})
            return
        if data.startswith("pub:dish:"):
            render(chat_id, user_id, {"view": "public_dish", "dish_id": UUID(data.split(":")[2])}, push=True)
            return

    @bot.message_handler(content_types=["text", "photo"])
    def handle_wizard_input(message: telebot.types.Message) -> None:
        delete_user_message(bot, message)
        session = get_session(message.chat.id, message.from_user.id)
        state = session.get("state")
        if not state:
            return
        text = (message.text or "").strip()
        draft = session.get("draft", {})

        if state and state.startswith("edit_dish_"):
            field = state.replace("edit_dish_", "")
            if field == "photo":
                if not message.photo:
                    send_or_edit(message.chat.id, message.from_user.id, "Отправьте фото блюда или нажмите «Пропустить», чтобы оставить текущее фото.", wizard_keyboard(message.chat.id, message.from_user.id))
                    return
                file_id = message.photo[-1].file_id
                file_info = bot.get_file(file_id)
                photo_bytes = bot.download_file(file_info.file_path)
                photo_object_key = photo_storage.put_bytes(photo_bytes)
                apply_dish_edit(message.chat.id, message.from_user, draft, field, photo_object_key)
                return
            if field == "price" and text and not text.isdigit():
                send_or_edit(message.chat.id, message.from_user.id, "Цена должна быть целым числом. Например: 2500. Либо нажмите «Пропустить».", wizard_keyboard(message.chat.id, message.from_user.id))
                return
            apply_dish_edit(message.chat.id, message.from_user, draft, field, text)
            return

        if state == "create_fr_title":
            draft["title"] = text
            go_to_step(message.chat.id, message.from_user.id, "create_fr_slug", draft)
            return
        if state == "create_fr_slug":
            draft["slug"] = text
            go_to_step(message.chat.id, message.from_user.id, "create_fr_description", draft)
            return
        if state == "create_fr_description":
            draft["description"] = None if text.lower() == "пропустить" else text
            error, franchise = service.create_franchise(CreateFranchiseCommand(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                title=draft.get("title", ""),
                slug=draft.get("slug", ""),
                description=draft.get("description"),
            ))
            clear_wizard(message.chat.id, message.from_user.id)
            if error or not franchise:
                send_or_edit(message.chat.id, message.from_user.id, error or "Не удалось создать франшизу.", keyboard([], back=True))
            else:
                render(message.chat.id, message.from_user.id, {"view": "franchise", "franchise_id": franchise.id})
            return
        if state == "branch_title":
            draft["title"] = text
            go_to_step(message.chat.id, message.from_user.id, "branch_address", draft)
            return
        if state == "branch_address":
            draft["address"] = None if text.lower() == "пропустить" else text
            go_to_step(message.chat.id, message.from_user.id, "branch_phone", draft)
            return
        if state == "branch_phone":
            draft["phone"] = None if text.lower() == "пропустить" else text
            error, branch = service.create_branch(CreateBranchCommand(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                franchise_id=draft["franchise_id"],
                title=draft.get("title", ""),
                address=draft.get("address"),
                phone=draft.get("phone"),
            ))
            clear_wizard(message.chat.id, message.from_user.id)
            if error or not branch:
                send_or_edit(message.chat.id, message.from_user.id, error or "Не удалось создать филиал.", keyboard([], back=True))
            else:
                render(message.chat.id, message.from_user.id, {"view": "branch", "branch_id": branch.id})
            return
        if state == "add_category":
            error, category = service.create_category(CreateCategoryCommand(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                branch_id=draft["branch_id"],
                title=text,
            ))
            branch_id = draft["branch_id"]
            clear_wizard(message.chat.id, message.from_user.id)
            if error:
                send_or_edit(message.chat.id, message.from_user.id, error, keyboard([], back=True))
            else:
                render(message.chat.id, message.from_user.id, {"view": "categories", "branch_id": branch_id})
            return
        if state == "dish_title":
            draft["title"] = text
            go_to_step(message.chat.id, message.from_user.id, "dish_description", draft)
            return
        if state == "dish_description":
            draft["description"] = None if text.lower() == "пропустить" else text
            go_to_step(message.chat.id, message.from_user.id, "dish_price", draft)
            return
        if state == "dish_price":
            if not text.isdigit():
                send_or_edit(message.chat.id, message.from_user.id, "Цена должна быть целым числом. Например: 2500. Если цену пока не нужно показывать, нажмите «Пропустить».", wizard_keyboard(message.chat.id, message.from_user.id))
                return
            draft["price"] = int(text)
            go_to_step(message.chat.id, message.from_user.id, "dish_weight", draft)
            return
        if state == "dish_weight":
            draft["weight"] = None if text.lower() == "пропустить" else text
            go_to_step(message.chat.id, message.from_user.id, "dish_photo", draft)
            return
        if state == "dish_photo":
            if message.photo:
                file_id = message.photo[-1].file_id
                file_info = bot.get_file(file_id)
                photo_bytes = bot.download_file(file_info.file_path)
                draft["photo_object_key"] = photo_storage.put_bytes(photo_bytes)
            elif text.lower() != "пропустить":
                send_or_edit(message.chat.id, message.from_user.id, "Отправьте фото блюда или нажмите «Пропустить».", wizard_keyboard(message.chat.id, message.from_user.id))
                return
            else:
                draft["photo_object_key"] = None
            go_to_step(message.chat.id, message.from_user.id, "dish_preview", draft)
            return

    @bot.message_handler(func=lambda message: True, content_types=["text", "photo", "document", "audio", "video", "voice", "sticker", "location", "contact"])
    def handle_cleanup_unmatched(message: telebot.types.Message) -> None:
        delete_user_message(bot, message)
