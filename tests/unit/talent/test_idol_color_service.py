import uuid
from unittest.mock import MagicMock

import pytest

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()

# ───────────────────────────────────────────────────────────────
# Idol Color Service Tests
# ───────────────────────────────────────────────────────────────

class TestIdolColorService:

    def test_add_idol_color_success(self):
        from app.schema.talent import IdolColorCreate
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        data = IdolColorCreate(name="Sakura Pink", hex_code="#FFB7C5")

        result = IdolColorService.add_idol_color(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_idol_colors_found(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = IdolColorService.get_idol_colors(db)
        assert len(result) == 1

    def test_get_idol_colors_empty(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.query().all.return_value = []

        result = IdolColorService.get_idol_colors(db)
        assert result == []

    def test_update_idol_color_success(self):
        from app.schema.talent import IdolColorBase
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = MagicMock()
        data = IdolColorBase(name="Midnight Blue", hex_code="#191970")

        result = IdolColorService.update_idol_color(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_idol_color_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.talent import IdolColorBase
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = None
        data = IdolColorBase(name="Midnight Blue", hex_code="#191970")

        with pytest.raises(NotFoundError):
            IdolColorService.update_idol_color(db, MISSING_ID, data)

    def test_delete_idol_color_success(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = MagicMock()

        result = IdolColorService.delete_idol_color(db, DEFAULT_ID)
        db.delete.assert_called_once()
        db.commit.assert_called_once()
        assert result is True

    def test_delete_idol_color_not_found(self):
        from app.services.talent.idol_color_service import IdolColorService

        db = MagicMock()
        db.get.return_value = None

        result = IdolColorService.delete_idol_color(db, MISSING_ID)
        assert result is False
