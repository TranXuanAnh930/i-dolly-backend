import re
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_api_reports_the_version():
    with patch("app.services.identity.auth_service.AuthService.cleanup_expired_tokens"):
        from main import app

        with TestClient(app) as client:
            assert client.get("/").json()["version"] == __version__
            assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_changelog_has_a_section_for_the_current_version():
    # Bumping __version__ without moving "Unreleased" into a release section fails here.
    for name in ("CHANGELOG.md", "CHANGELOG_JP.md"):
        assert f"## {__version__} — " in (ROOT / name).read_text(encoding="utf-8")
