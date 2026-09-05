"""Image storage abstraction — local filesystem for now, swappable for S3
(or any S3-compatible provider: DigitalOcean Spaces, Cloudflare R2, MinIO,
...) for deploy via a single env var (STORAGE_BACKEND), no code changes at
any call site.

Every backend implements the same interface: save(upload_file, subfolder)
-> public URL string. Callers (app/router/idol.py, app/router/products.py)
only ever go through get_storage() — they never know or care which backend
is actually active.
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
    """Raised for any upload failure the router should turn into a 400 —
    an unsupported content type, an oversized file, or a misconfigured
    backend (e.g. S3_BUCKET_NAME missing when STORAGE_BACKEND=s3)."""


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, file: UploadFile, subfolder: str) -> str:
        """Persist `file` under `subfolder` (e.g. "idols", "products") and
        return its public URL — a local /uploads/... path, or a full S3/CDN
        URL, depending on the backend. Raises StorageError on any failure."""


def _new_filename(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise StorageError(
            f"Unsupported image type: {file.content_type!r}. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_CONTENT_TYPES))}"
        )
    # Never trust the client-supplied filename for the path we write to —
    # only its extension, and only from an already-whitelisted content type.
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    return f"{uuid.uuid4().hex}{ext}"


class LocalStorageBackend(StorageBackend):
    """Saves under LOCAL_UPLOAD_DIR, served back out by main.py's
    StaticFiles mount at LOCAL_UPLOAD_URL_PREFIX. Good for local dev — and,
    since docker-compose.yaml already bind-mounts the whole app directory,
    files written here land on the host and survive container restarts too.
    Not durable for a real deploy on an ephemeral/multi-instance filesystem
    though (a redeploy or a second instance won't see what the first one
    saved) — that's exactly what S3StorageBackend is for."""

    def __init__(self):
        self.root = Path(settings.LOCAL_UPLOAD_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, file: UploadFile, subfolder: str) -> str:
        filename = _new_filename(file)
        dest_dir = self.root / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        size = 0
        try:
            with open(dest_path, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise StorageError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit")
                    out.write(chunk)
        except StorageError:
            dest_path.unlink(missing_ok=True)
            raise

        return f"{settings.LOCAL_UPLOAD_URL_PREFIX.rstrip('/')}/{subfolder}/{filename}"


class S3StorageBackend(StorageBackend):
    """Uploads to an S3 (or S3-compatible) bucket. boto3 is imported lazily
    here rather than at module level, so it's only a hard dependency at
    runtime when STORAGE_BACKEND=s3 is actually selected — local-only dev
    doesn't need it configured (it does need it installed either way, since
    it's in requirements.txt, but never imported/executed for local dev)."""

    def __init__(self):
        import boto3  # local import — see class docstring

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

    async def save(self, file: UploadFile, subfolder: str) -> str:
        filename = _new_filename(file)
        key = f"{subfolder}/{filename}"

        data = await file.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise StorageError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit")

        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=file.content_type)
        return self._public_url(key)

    def _public_url(self, key: str) -> str:
        if settings.S3_PUBLIC_URL_BASE:
            return f"{settings.S3_PUBLIC_URL_BASE.rstrip('/')}/{key}"
        if settings.S3_ENDPOINT_URL:
            # S3-compatible provider (DO Spaces, R2, MinIO, ...) — path-style URL.
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{self.bucket}/{key}"
        region_part = f".{settings.S3_REGION}" if settings.S3_REGION and settings.S3_REGION != "us-east-1" else ""
        return f"https://{self.bucket}.s3{region_part}.amazonaws.com/{key}"


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Lazily instantiate the configured backend once per process. Routers
    call this, never a backend class directly."""
    global _backend
    if _backend is None:
        if settings.STORAGE_BACKEND == "s3":
            _backend = S3StorageBackend()
        else:
            _backend = LocalStorageBackend()
    return _backend
