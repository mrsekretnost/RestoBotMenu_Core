from __future__ import annotations

from telebot import types

BTN_PUBLIC_MENU = "Открыть меню"
BTN_ADMIN_PANEL = "Админка"
BTN_HELP = "Помощь"


def build_main_menu_keyboard(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row(BTN_PUBLIC_MENU)
    if is_admin:
        keyboard.row(BTN_ADMIN_PANEL)
    keyboard.row(BTN_HELP)
    return keyboard


def build_main_inline_keyboard(is_admin: bool = False) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton(text="Открыть меню", callback_data="main:menu"))
    if is_admin:
        markup.row(types.InlineKeyboardButton(text="Админка", callback_data="main:admin"))
    markup.row(types.InlineKeyboardButton(text="Помощь", callback_data="main:help"))
    return markup
