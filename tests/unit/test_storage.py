import io

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.utils.storage import StorageError, _new_filename


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
