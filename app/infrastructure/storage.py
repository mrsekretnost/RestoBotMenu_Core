from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

try:
    from minio import Minio
except Exception:  # pragma: no cover
    Minio = None  # type: ignore


@dataclass(slots=True)
class StorageSettings:
    backend: str
    local_dir: str
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_secure: bool = False


class PhotoStorage:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self.local_dir = Path(settings.local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        if settings.backend == "minio":
            if Minio is None:
                raise RuntimeError("Для MinIO нужно установить пакет minio")
            if not settings.minio_endpoint or not settings.minio_access_key or not settings.minio_secret_key or not settings.minio_bucket:
                raise RuntimeError("Для MinIO нужны MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY и MINIO_BUCKET")
            self._client = Minio(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if not self._client.bucket_exists(settings.minio_bucket):
                self._client.make_bucket(settings.minio_bucket)

    def build_object_key(self, suffix: str = ".jpg") -> str:
        return f"dishes/{uuid4().hex}{suffix}"

    def put_bytes(self, data: bytes, object_key: str | None = None, content_type: str = "image/jpeg") -> str:
        key = object_key or self.build_object_key()
        if self.settings.backend == "minio":
            assert self._client is not None
            assert self.settings.minio_bucket is not None
            self._client.put_object(
                self.settings.minio_bucket,
                key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"minio://{self.settings.minio_bucket}/{key}"

        path = self.local_dir.joinpath(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local://{path.as_posix()}"

    def get_photo_source(self, stored_key: str | None) -> str | BytesIO | None:
        if not stored_key:
            return None

        # Backward compatibility with old Telegram file_id values.
        if not stored_key.startswith("minio://") and not stored_key.startswith("local://"):
            return stored_key

        if stored_key.startswith("local://"):
            path = Path(stored_key.removeprefix("local://"))
            if path.exists():
                return BytesIO(path.read_bytes())
            return None

        if stored_key.startswith("minio://"):
            assert self._client is not None
            _, rest = stored_key.split("minio://", 1)
            bucket, object_name = rest.split("/", 1)
            return self._client.presigned_get_object(bucket, object_name)

        return None
