import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.exception.common import BadRequestError, ForbiddenError, NotFoundError

# ───────────────────────────────────────────────────────────────
# Id sentinels — plain MagicMock-based unit tests (no real DB), so any
# distinct UUIDs work: DEFAULT_ID stands in for "the id under test",
# OTHER_ID for "a second, different row", MISSING_ID for "doesn't exist".
# ───────────────────────────────────────────────────────────────

DEFAULT_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()
# Stand-in for any *Read schema's created_at/updated_at — real value never
# matters to these tests, only that it's a real datetime, not an
# auto-vivified MagicMock attribute a from_attributes schema can't validate.
DEFAULT_TIMESTAMP = datetime.now(timezone.utc)

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_user(id=DEFAULT_ID, name="Test", email="test@example.com", is_admin=False, is_verified=True, role="fan"):
    user = MagicMock()
    user.id = id
    user.name = name
    user.email = email
    user.is_admin = is_admin
    user.is_verified = is_verified
    user.hashed_password = "$2b$12$hashedpassword"
    user.role = role  # matches Users.role's real DB default (database-design.md §3.1)
    return user

def make_mock_manager(id=DEFAULT_ID, company_id=DEFAULT_ID, name="Manager", email="manager@example.com"):
    user = make_mock_user(id=id, name=name, email=email, role="manager")
    user.company_id = company_id
    return user

def make_mock_group(id=DEFAULT_ID, company_id=DEFAULT_ID, name="Prism", is_active=True):
    group = MagicMock()
    group.id = id
    group.company_id = company_id
    group.name = name
    group.is_active = is_active
    group.debut_date = None
    group.description = None
    group.created_at = DEFAULT_TIMESTAMP
    group.updated_at = DEFAULT_TIMESTAMP
    return group

def make_mock_idol(id=DEFAULT_ID, company_id=DEFAULT_ID, group_id=None, color_id=None, is_active=True, name="Idol"):
    idol = MagicMock()
    idol.id = id
    idol.company_id = company_id
    idol.group_id = group_id
    idol.color_id = color_id
    idol.is_active = is_active
    idol.name = name
    idol.date_of_birth = None
    idol.hometown = None
    idol.short_intro = None
    idol.long_description = None
    idol.profile_image_url = None
    idol.created_at = DEFAULT_TIMESTAMP
    idol.updated_at = DEFAULT_TIMESTAMP
    idol.idol_positions = []
    idol.color = None
    idol.group = None
    return idol

def model_get_side_effect(mapping: dict):
    """Builds a db.get(Model, id) side_effect that dispatches on the model
    class, since a plain MagicMock().get ignores call args and can't tell
    db.get(Product, ...) apart from db.get(AlbumDetail, ...) on its own."""
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect


# ───────────────────────────────────────────────────────────────
# Marketplace domain: Album Detail Service Tests
# ───────────────────────────────────────────────────────────────

class TestAlbumDetailService:

    def test_add_album_detail_success_with_idol(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, track_count=10)

        result = AlbumDetailService.add_album_detail(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_album_detail_success_with_group(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Group
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Group: mock_group})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        result = AlbumDetailService.add_album_detail(db, data, current_user)
        assert result is not None

    def test_add_album_detail_product_not_found(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: None})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=MISSING_ID, idol_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_conflict(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_artist_inactive(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        inactive_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: inactive_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_add_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailCreate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), AlbumDetail: None, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.add_album_detail(db, data, current_user)

    def test_get_album_detail_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock()
        db.get.return_value = mock_album

        result = AlbumDetailService.get_album_detail(db, DEFAULT_ID)
        assert result == mock_album

    def test_get_album_detail_not_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.return_value = None

        result = AlbumDetailService.get_album_detail(db, MISSING_ID)
        assert result is None

    def test_get_album_details_found(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = AlbumDetailService.get_album_details(db)
        assert len(result) == 1

    def test_get_album_details_empty(self):
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.query().all.return_value = []

        result = AlbumDetailService.get_album_details(db)
        assert result is False

    def test_update_album_detail_success(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailUpdate(track_count=12)

        result = AlbumDetailService.update_album_detail(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_album_detail_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")
        data = AlbumDetailUpdate(track_count=12)

        with pytest.raises(NotFoundError):
            AlbumDetailService.update_album_detail(db, MISSING_ID, data, current_user)

    def test_update_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumDetailUpdate
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumDetailUpdate(track_count=12)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.update_album_detail(db, DEFAULT_ID, data, current_user)

    def test_delete_album_detail_success(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_user(role="admin")

        result = AlbumDetailService.delete_album_detail(db, DEFAULT_ID, current_user)
        assert result is mock_album
        db.delete.assert_called_once_with(mock_album)

    def test_delete_album_detail_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            AlbumDetailService.delete_album_detail(db, MISSING_ID, current_user)

    def test_delete_album_detail_forbidden(self):
        from app.db.models.marketplace import AlbumDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.album_detail_service import AlbumDetailService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            AlbumDetailService.delete_album_detail(db, DEFAULT_ID, current_user)
