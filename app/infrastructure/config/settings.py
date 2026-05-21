from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    database_path: str
    debug: bool = False
    storage_backend: str = "local"
    storage_local_dir: str = "data/photos"
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is required")

        database_path = os.getenv("DATABASE_PATH", "data/restaurant_menu_bot.sqlite3").strip()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

        debug = os.getenv("DEBUG", "false").lower() in {"1", "true", "yes", "on"}
        storage_backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
        storage_local_dir = os.getenv("STORAGE_LOCAL_DIR", "data/photos").strip()
        Path(storage_local_dir).mkdir(parents=True, exist_ok=True)
        minio_secure = os.getenv("MINIO_SECURE", "false").lower() in {"1", "true", "yes", "on"}
        return cls(
            bot_token=token,
            database_path=database_path,
            debug=debug,
            storage_backend=storage_backend,
            storage_local_dir=storage_local_dir,
            minio_endpoint=os.getenv("MINIO_ENDPOINT"),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY"),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY"),
            minio_bucket=os.getenv("MINIO_BUCKET"),
            minio_secure=minio_secure,
        )
