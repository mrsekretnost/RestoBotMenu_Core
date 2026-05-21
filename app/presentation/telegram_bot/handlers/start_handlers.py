from __future__ import annotations

import telebot
from telebot import types

from app.application.dto import ActorCommand
from app.application.services.restaurant_service import RestaurantService
from app.presentation.telegram_bot.message_utils import delete_user_message, edit_callback_message, send_or_edit_message
from app.presentation.telegram_bot.keyboards.reply import BTN_HELP, BTN_PUBLIC_MENU, build_main_inline_keyboard


def register_start_handlers(bot: telebot.TeleBot, service: RestaurantService) -> None:
    def actor_from_user(user: telebot.types.User) -> ActorCommand:
        return ActorCommand(telegram_id=user.id, username=user.username, first_name=user.first_name)

    def actor(message: telebot.types.Message) -> ActorCommand:
        return actor_from_user(message.from_user)

    def keyboard_for(message: telebot.types.Message):
        is_admin = service.is_admin(message.from_user.id, message.from_user.username, message.from_user.first_name)
        return build_main_inline_keyboard(is_admin=is_admin)

    def owner_setup_markup() -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton(text="Стать владельцем", callback_data="owner:claim_confirm"))
        return markup

    def owner_confirm_markup() -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton(text="Подтвердить", callback_data="owner:claim"))
        markup.row(types.InlineKeyboardButton(text="Отмена", callback_data="owner:cancel"))
        return markup

    def send_owner_setup_if_available(message: telebot.types.Message) -> bool:
        is_open, minutes_left, _error = service.owner_setup_status()
        if not is_open:
            return False
        text = (
            "Владелец ещё не назначен.\n\n"
            "Первый владелец получает полный доступ к управлению ботом и сможет добавлять младших администраторов.\n"
            f"Назначение доступно ещё примерно {minutes_left} мин."
        )
        send_or_edit_message(bot, message.chat.id, message.from_user.id, text, reply_markup=owner_setup_markup())
        return True

    def send_start_message(message: telebot.types.Message) -> None:
        payload = ""
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                payload = parts[1].strip()

        if payload.startswith("admin_invite_"):
            result = service.claim_admin_invite(actor(message), payload[13:])
            send_or_edit_message(bot, message.chat.id, message.from_user.id, result, reply_markup=keyboard_for(message))
            return

        if send_owner_setup_if_available(message):
            return

        text = (
            "Привет! Это бот ресторанного меню.\n\n"
            "Нажмите кнопку «Открыть меню», чтобы выбрать филиал и посмотреть блюда."
        )
        send_or_edit_message(bot, message.chat.id, message.from_user.id, text, reply_markup=keyboard_for(message))

    def send_help_message(message: telebot.types.Message) -> None:
        text = (
            "Как открыть меню:\n\n"
            "Нажмите кнопку «Открыть меню» или отправьте команду /menu.\n"
            "После этого бот покажет филиалы ресторана."
        )
        send_or_edit_message(bot, message.chat.id, message.from_user.id, text, reply_markup=keyboard_for(message))

    @bot.message_handler(commands=["start"])
    def handle_start(message: telebot.types.Message) -> None:
        send_start_message(message)
        delete_user_message(bot, message)

    @bot.message_handler(commands=["help"])
    def handle_help(message: telebot.types.Message) -> None:
        send_help_message(message)
        delete_user_message(bot, message)

    @bot.message_handler(func=lambda message: message.text == BTN_HELP)
    def handle_help_button(message: telebot.types.Message) -> None:
        send_help_message(message)
        delete_user_message(bot, message)


    @bot.callback_query_handler(func=lambda call: (call.data or "").startswith("main:"))
    def handle_main_callback(call: telebot.types.CallbackQuery) -> None:
        data = call.data or ""
        bot.answer_callback_query(call.id)
        if data == "main:help":
            text = (
                "Как открыть меню:\n\n"
                "Нажмите кнопку «Открыть меню». После этого бот покажет филиалы ресторана."
            )
            is_admin = service.is_admin(call.from_user.id, call.from_user.username, call.from_user.first_name)
            edit_callback_message(bot, call, text, reply_markup=build_main_inline_keyboard(is_admin=is_admin))
            return
        if data == "main:menu":
            from app.presentation.telegram_bot.handlers.restaurant_handlers import open_public_menu_from_start
            open_public_menu_from_start(bot, service, call.message.chat.id, call.from_user.id)
            return
        if data == "main:admin":
            from app.presentation.telegram_bot.handlers.restaurant_handlers import open_admin_from_start
            open_admin_from_start(bot, service, call.message.chat.id, call.from_user.id, call.from_user)
            return

    @bot.callback_query_handler(func=lambda call: (call.data or "").startswith("owner:"))
    def handle_owner_setup_callback(call: telebot.types.CallbackQuery) -> None:
        data = call.data or ""
        bot.answer_callback_query(call.id)
        if data == "owner:cancel":
            edit_callback_message(bot, call, "Назначение владельца отменено.")
            return
        if data == "owner:claim_confirm":
            is_open, minutes_left, error = service.owner_setup_status()
            if not is_open:
                edit_callback_message(bot, call, error or "Назначение владельца недоступно.")
                return
            text = (
                "Подтвердите назначение владельца.\n\n"
                "После подтверждения повторно назначить владельца через первичную настройку будет невозможно.\n"
                f"Осталось примерно {minutes_left} мин."
            )
            edit_callback_message(bot, call, text, reply_markup=owner_confirm_markup())
            return
        if data == "owner:claim":
            result = service.claim_first_owner(actor_from_user(call.from_user))
            is_admin = service.is_admin(call.from_user.id, call.from_user.username, call.from_user.first_name)
            edit_callback_message(bot, call, result + "\n\nГлавное меню обновлено.", reply_markup=build_main_inline_keyboard(is_admin=is_admin))
            return
