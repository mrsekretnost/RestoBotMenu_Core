from __future__ import annotations

from app.infrastructure.config.settings import Settings
from app.infrastructure.db.connection import Database
from app.presentation.telegram_bot.bot import create_bot_app


def run() -> None:
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.ping()
    database.ensure_schema()
    bot_app = create_bot_app(settings, database)
    bot_app.run()
