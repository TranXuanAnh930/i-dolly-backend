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
# Category Service Tests
# ───────────────────────────────────────────────────────────────

class TestCategoryService:

    def test_add_category(self):
        from app.schema.marketplace import CategoryBase
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        cat_data = CategoryBase(name="Electronics")

        CategoryService.add_categories(db, cat_data)
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_get_categories(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(id=DEFAULT_ID, name="Electronics")]

        result = CategoryService.get_categories(db)
        assert len(result) == 1

    def test_get_categories_empty(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.query().all.return_value = []

        result = CategoryService.get_categories(db)
        assert result == []

    def test_update_category_success(self):
        from app.schema.marketplace import CategoryUpdate
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        mock_cat = MagicMock()
        db.get.return_value = mock_cat

        result = CategoryService.update_category(db, DEFAULT_ID, CategoryUpdate(name="Updated"))
        assert result is not None
        db.commit.assert_called_once()

    def test_update_category_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.marketplace import CategoryUpdate
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            CategoryService.update_category(db, MISSING_ID, CategoryUpdate(name="Nope"))

    def test_delete_category_success(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        mock_cat = MagicMock()
        db.get.return_value = mock_cat
        db.query.return_value.filter.return_value.first.return_value = None  # no products in it

        result = CategoryService.delete_category(db, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once()

    def test_delete_category_with_products_is_refused(self):
        # bugs.md #2: deleting it would delete its products, and their order history with them.
        from app.exception.common import BadRequestError
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.get.return_value = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = (DEFAULT_ID,)

        with pytest.raises(BadRequestError) as exc_info:
            CategoryService.delete_category(db, DEFAULT_ID)

        assert exc_info.value.code == "category_in_use"
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    def test_delete_category_not_found(self):
        from app.services.marketplace.category_service import CategoryService

        db = MagicMock()
        db.get.return_value = None

        result = CategoryService.delete_category(db, MISSING_ID)
        assert result is False
