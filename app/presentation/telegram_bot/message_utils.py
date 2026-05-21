from __future__ import annotations

from io import BytesIO

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

_last_bot_messages: dict[tuple[int, int], int] = {}


def remember_bot_message(chat_id: int, user_id: int, message_id: int) -> None:
    _last_bot_messages[(chat_id, user_id)] = message_id


def get_last_bot_message_id(chat_id: int, user_id: int) -> int | None:
    return _last_bot_messages.get((chat_id, user_id))


def delete_user_message(bot: telebot.TeleBot, message: telebot.types.Message | None) -> None:
    if not message:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except ApiTelegramException:
        pass
    except Exception:
        pass


def _delete_previous(bot: telebot.TeleBot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException:
        pass
    except Exception:
        pass


def send_or_edit_message(
    bot: telebot.TeleBot,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    photo: str | BytesIO | None = None,
) -> None:
    message_id = get_last_bot_message_id(chat_id, user_id)

    if photo:
        caption = text[:1024]
        if isinstance(photo, str) and message_id:
            try:
                bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=types.InputMediaPhoto(media=photo, caption=caption),
                    reply_markup=reply_markup,
                )
                return
            except ApiTelegramException:
                pass
            except Exception:
                pass

        _delete_previous(bot, chat_id, message_id)
        if isinstance(photo, BytesIO):
            photo.seek(0)
        msg = bot.send_photo(chat_id, photo, caption=caption, reply_markup=reply_markup)
        remember_bot_message(chat_id, user_id, msg.message_id)
        return

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
            return
        except ApiTelegramException:
            pass

    _delete_previous(bot, chat_id, message_id)
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup)
    remember_bot_message(chat_id, user_id, msg.message_id)


def edit_callback_message(
    bot: telebot.TeleBot,
    call: telebot.types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> None:
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=reply_markup)
        remember_bot_message(call.message.chat.id, call.from_user.id, call.message.message_id)
    except ApiTelegramException:
        send_or_edit_message(bot, call.message.chat.id, call.from_user.id, text, reply_markup=reply_markup)
