"""Image storage: local filesystem or S3-compatible bucket, selected by STORAGE_BACKEND.

Callers use get_storage().save(upload, subfolder), which returns the file's public URL.
save() is synchronous: Starlette has already spooled the upload into UploadFile.file before the
handler runs, and the calling routes are `def` (they run in the threadpool).
"""
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from fastapi import UploadFile

from app.config.settings import settings

ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class StorageError(Exception):
    """An upload failure to report as 400: bad content type, oversized file, or misconfiguration."""


class StorageBackend(ABC):
    @abstractmethod
    def save(self, file: UploadFile, subfolder: str) -> str:
        """Store `file` under `subfolder` and return its public URL. Raises StorageError."""


def _new_filename(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise StorageError(
            f"Unsupported image type: {file.content_type!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_CONTENT_TYPES))}"
        )
    # Random filename; only the extension comes from the client.
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    return f"{uuid.uuid4().hex}{ext}"


class LocalStorageBackend(StorageBackend):
    """Saves under LOCAL_UPLOAD_DIR, served by main.py's StaticFiles mount. Not durable on
    ephemeral or multi-instance hosts; use S3StorageBackend there."""

    def __init__(self) -> None:
        self.root = Path(settings.LOCAL_UPLOAD_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, file: UploadFile, subfolder: str) -> str:
        filename = _new_filename(file)
        dest_dir = self.root / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        size = 0
        try:
            with open(dest_path, "wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise StorageError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit")
                    out.write(chunk)
        except StorageError:
            dest_path.unlink(missing_ok=True)
            raise

        return f"{settings.LOCAL_UPLOAD_URL_PREFIX.rstrip('/')}/{subfolder}/{filename}"


class S3StorageBackend(StorageBackend):
    """Uploads to S3 or an S3-compatible provider. boto3 is imported only when this backend is used."""

    def __init__(self) -> None:
        import boto3

        if not settings.S3_BUCKET_NAME:
            raise StorageError("STORAGE_BACKEND=s3 but S3_BUCKET_NAME is not set")

        self.bucket = settings.S3_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            region_name=settings.S3_REGION or None,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
        )

    def save(self, file: UploadFile, subfolder: str) -> str:
        filename = _new_filename(file)
        key = f"{subfolder}/{filename}"

        # UploadFile.read() is async, so read the underlying file. Reading one byte past the limit
        # detects oversized uploads without loading the whole file.
        data = file.file.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise StorageError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit")

        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=file.content_type)
        return self._public_url(key)

    def _public_url(self, key: str) -> str:
        if settings.S3_PUBLIC_URL_BASE:
            return f"{settings.S3_PUBLIC_URL_BASE.rstrip('/')}/{key}"
        if settings.S3_ENDPOINT_URL:
            # S3-compatible provider: path-style URL.
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.bucket}/{key}"
        region_part = f".{settings.S3_REGION}" if settings.S3_REGION and settings.S3_REGION != "us-east-1" else ""
        return f"https://{self.bucket}.s3{region_part}.amazonaws.com/{key}"


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured backend, created once per process."""
    global _backend
    if _backend is None:
        if settings.STORAGE_BACKEND == "s3":
            _backend = S3StorageBackend()
        else:
            _backend = LocalStorageBackend()
    return _backend
