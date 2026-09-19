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
# Marketplace domain: Merch Detail Service Tests
# ───────────────────────────────────────────────────────────────

class TestMerchDetailService:

    def test_add_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, edition="Limited")

        result = MerchDetailService.add_merch_detail(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_merch_detail_product_not_found(self):
        from app.db.models.marketplace import Product
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=MISSING_ID, group_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_conflict(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_color_not_found(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import IdolColor
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID, color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_artist_inactive(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Group
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Group: inactive_group})
        current_user = make_mock_user(role="admin")
        data = MerchDetailCreate(product_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_add_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail, Product
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailCreate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({Product: MagicMock(), MerchDetail: None, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = MerchDetailCreate(product_id=DEFAULT_ID, idol_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            MerchDetailService.add_merch_detail(db, data, current_user)

    def test_get_merch_detail_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock()
        db.get.return_value = mock_merch

        result = MerchDetailService.get_merch_detail(db, DEFAULT_ID)
        assert result == mock_merch

    def test_get_merch_detail_not_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.return_value = None

        result = MerchDetailService.get_merch_detail(db, MISSING_ID)
        assert result is None

    def test_get_merch_details_found(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = MerchDetailService.get_merch_details(db)
        assert len(result) == 1

    def test_get_merch_details_empty(self):
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.query().all.return_value = []

        result = MerchDetailService.get_merch_details(db)
        assert result == []

    def test_update_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue")

        result = MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_merch_detail_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({MerchDetail: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue")

        with pytest.raises(NotFoundError):
            MerchDetailService.update_merch_detail(db, MISSING_ID, data, current_user)

    def test_update_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = MerchDetailUpdate(edition="Reissue")

        with pytest.raises(ForbiddenError):
            MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)

    def test_update_merch_detail_color_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol, IdolColor
        from app.schema.marketplace import MerchDetailUpdate
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol, IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = MerchDetailUpdate(edition="Reissue", color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            MerchDetailService.update_merch_detail(db, DEFAULT_ID, data, current_user)

    def test_delete_merch_detail_success(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_user(role="admin")

        result = MerchDetailService.delete_merch_detail(db, DEFAULT_ID, current_user)
        assert result is mock_merch
        db.delete.assert_called_once_with(mock_merch)

    def test_delete_merch_detail_not_found(self):
        from app.db.models.marketplace import MerchDetail
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({MerchDetail: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            MerchDetailService.delete_merch_detail(db, MISSING_ID, current_user)

    def test_delete_merch_detail_forbidden(self):
        from app.db.models.marketplace import MerchDetail
        from app.db.models.talent import Idol
        from app.services.marketplace.merch_detail_service import MerchDetailService

        db = MagicMock()
        mock_merch = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({MerchDetail: mock_merch, Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            MerchDetailService.delete_merch_detail(db, DEFAULT_ID, current_user)
