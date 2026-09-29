import io
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.utils.storage import StorageError, _new_filename

STORAGE = "app.utils.storage"


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"data"),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


class TestNewFilename:
    @pytest.mark.parametrize(
        ("content_type", "ext"),
        [("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp"), ("image/gif", ".gif")],
    )
    def test_extension_follows_content_type(self, content_type, ext):
        assert _new_filename(_upload("photo", content_type)).endswith(ext)

    @pytest.mark.parametrize("filename", ["evil.html", "evil.svg", "evil.png.html", "noext"])
    def test_client_filename_extension_is_ignored(self, filename):
        name = _new_filename(_upload(filename, "image/png"))
        assert name.endswith(".png")
        assert ".html" not in name and ".svg" not in name

    def test_unsupported_content_type_rejected(self):
        with pytest.raises(StorageError):
            _new_filename(_upload("evil.html", "text/html"))


class TestLocalStorageBackend:
    @pytest.fixture
    def backend(self, tmp_path):
        from app.utils.storage import LocalStorageBackend

        with patch(f"{STORAGE}.settings.LOCAL_UPLOAD_DIR", str(tmp_path)), \
             patch(f"{STORAGE}.settings.LOCAL_UPLOAD_URL_PREFIX", "/uploads/"):
            yield LocalStorageBackend(), tmp_path

    def test_saves_file_and_returns_public_url(self, backend):
        storage, root = backend
        url = storage.save(_upload("photo.png", "image/png"), subfolder="idols")

        assert url.startswith("/uploads/idols/") and url.endswith(".png")
        saved = root / "idols" / url.rsplit("/", 1)[1]
        assert saved.read_bytes() == b"data"

    def test_oversized_file_rejected_and_removed(self, backend):
        storage, root = backend
        with patch(f"{STORAGE}.MAX_IMAGE_BYTES", 2):
            with pytest.raises(StorageError, match="limit"):
                storage.save(_upload("photo.png", "image/png"), subfolder="products")
        assert list((root / "products").iterdir()) == []


class TestS3StorageBackend:
    @pytest.fixture
    def make_backend(self, monkeypatch):
        """Build an S3StorageBackend with a mocked boto3 client; returns (backend, client)."""
        from app.utils import storage

        def _make(**overrides):
            config = {
                "S3_BUCKET_NAME": "bucket", "S3_REGION": "us-east-1", "S3_ENDPOINT_URL": None,
                "S3_PUBLIC_URL_BASE": None, "AWS_ACCESS_KEY_ID": None, "AWS_SECRET_ACCESS_KEY": None,
            } | overrides
            for key, value in config.items():
                monkeypatch.setattr(storage.settings, key, value)
            with patch("boto3.client") as client_factory:
                return storage.S3StorageBackend(), client_factory.return_value

        return _make

    def test_missing_bucket_rejected(self, make_backend):
        with pytest.raises(StorageError, match="S3_BUCKET_NAME"):
            make_backend(S3_BUCKET_NAME=None)

    def test_save_uploads_object_and_returns_aws_url(self, make_backend):
        backend, client = make_backend()
        url = backend.save(_upload("photo.jpg", "image/jpeg"), subfolder="products")

        put = client.put_object
        put.assert_called_once()
        kwargs = put.call_args.kwargs
        assert kwargs["Bucket"] == "bucket" and kwargs["Body"] == b"data" and kwargs["ContentType"] == "image/jpeg"
        assert url == f"https://bucket.s3.amazonaws.com/{kwargs['Key']}"
        assert kwargs["Key"].startswith("products/") and kwargs["Key"].endswith(".jpg")

    def test_oversized_file_rejected_without_upload(self, make_backend):
        backend, client = make_backend()
        with patch(f"{STORAGE}.MAX_IMAGE_BYTES", 2):
            with pytest.raises(StorageError, match="limit"):
                backend.save(_upload("photo.png", "image/png"), subfolder="products")
        client.put_object.assert_not_called()

    @pytest.mark.parametrize(
        ("overrides", "expected_prefix"),
        [
            ({"S3_REGION": "ap-northeast-1"}, "https://bucket.s3.ap-northeast-1.amazonaws.com/"),
            ({"S3_ENDPOINT_URL": "https://r2.example.com/"}, "https://r2.example.com/bucket/"),
            ({"S3_PUBLIC_URL_BASE": "https://cdn.example.com/", "S3_ENDPOINT_URL": "https://r2.example.com"}, "https://cdn.example.com/"),
        ],
    )
    def test_public_url_variants(self, make_backend, overrides, expected_prefix):
        backend, _ = make_backend(**overrides)
        assert backend._public_url("products/x.png") == f"{expected_prefix}products/x.png"


class TestGetStorage:
    @pytest.fixture(autouse=True)
    def fresh_backend(self):
        with patch(f"{STORAGE}._backend", None):
            yield

    def test_local_by_default_and_cached(self, tmp_path):
        from app.utils.storage import LocalStorageBackend, get_storage

        with patch(f"{STORAGE}.settings.STORAGE_BACKEND", "local"), \
             patch(f"{STORAGE}.settings.LOCAL_UPLOAD_DIR", str(tmp_path)):
            first = get_storage()
            assert isinstance(first, LocalStorageBackend)
            assert get_storage() is first

    def test_s3_when_configured(self):
        from app.utils.storage import get_storage

        with patch(f"{STORAGE}.settings.STORAGE_BACKEND", "s3"), \
             patch(f"{STORAGE}.S3StorageBackend") as s3_backend:
            assert get_storage() is s3_backend.return_value
