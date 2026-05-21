from __future__ import annotations

import os

import telebot
from telebot import apihelper

from app.application.services.restaurant_service import RestaurantService
from app.infrastructure.config.settings import Settings
from app.infrastructure.db.connection import Database
from app.infrastructure.db.repositories.restaurant_repository import RestaurantRepository
from app.infrastructure.storage import PhotoStorage, StorageSettings
from app.presentation.telegram_bot.handlers.restaurant_handlers import register_restaurant_handlers
from app.presentation.telegram_bot.handlers.start_handlers import register_start_handlers


class TelegramBotApp:
    def __init__(self, bot: telebot.TeleBot) -> None:
        self.bot = bot

    def run(self) -> None:
        self.bot.infinity_polling(skip_pending=True, timeout=10, long_polling_timeout=10)


def create_bot_app(settings: Settings, database: Database) -> TelegramBotApp:
    for var_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(var_name, None)

    bot = telebot.TeleBot(settings.bot_token, threaded=False)
    apihelper.proxy = {}
    apihelper._get_req_session().trust_env = False

    repository = RestaurantRepository(database)
    service = RestaurantService(repository)
    photo_storage = PhotoStorage(StorageSettings(
        backend=settings.storage_backend,
        local_dir=settings.storage_local_dir,
        minio_endpoint=settings.minio_endpoint,
        minio_access_key=settings.minio_access_key,
        minio_secret_key=settings.minio_secret_key,
        minio_bucket=settings.minio_bucket,
        minio_secure=settings.minio_secure,
    ))

    bot.set_my_commands([
        telebot.types.BotCommand("start", "Запустить бота"),
        telebot.types.BotCommand("menu", "Открыть меню"),
        telebot.types.BotCommand("help", "Помощь"),
    ])

    register_start_handlers(bot, service)
    register_restaurant_handlers(bot, service, photo_storage)

    return TelegramBotApp(bot)
