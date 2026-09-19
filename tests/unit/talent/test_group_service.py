import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.exception.common import ForbiddenError, NotFoundError

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

def make_mock_company(id=DEFAULT_ID, name="Nova Entertainment"):
    company = MagicMock()
    company.id = id
    company.name = name
    return company

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

def make_mock_venue(id=DEFAULT_ID, name="Arena"):
    venue = MagicMock()
    venue.id = id
    venue.name = name
    venue.address = "1 Main St"
    venue.city = "Seoul"
    venue.country = "KR"
    venue.total_capacity = 1000
    venue.contact_info = None
    venue.size = "large"
    venue.created_at = DEFAULT_TIMESTAMP
    return venue

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID, venue=None):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    concert.venue_id = venue.id if venue else DEFAULT_ID
    concert.title = "Concert"
    concert.description = None
    concert.capacity = 500
    concert.event_datetime = DEFAULT_TIMESTAMP
    concert.doors_open_at = None
    concert.status = "scheduled"
    concert.created_at = DEFAULT_TIMESTAMP
    concert.updated_at = DEFAULT_TIMESTAMP
    concert.venue = venue if venue else make_mock_venue(id=concert.venue_id)
    return concert


# ───────────────────────────────────────────────────────────────
# Talent domain: Group Service Tests
# ───────────────────────────────────────────────────────────────

class TestGroupService:

    def test_add_group_success(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        current_user = make_mock_user(role="admin")
        data = GroupCreate(name="Prism Sirens", company_id=DEFAULT_ID)

        result = GroupService.add_group(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_group_forbidden(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        current_user = make_mock_manager(company_id=OTHER_ID)
        data = GroupCreate(name="Prism Sirens", company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.add_group(db, data, current_user)
        db.add.assert_not_called()

    def test_add_group_company_not_found(self):
        from app.schema.talent import GroupCreate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = GroupCreate(name="Prism Sirens", company_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            GroupService.add_group(db, data, current_user)

    def test_get_groups_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_group()]

        result = GroupService.get_groups(db)
        assert len(result) == 1

    def test_get_groups_empty(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GroupService.get_groups(db)
        assert result is None

    def test_get_group(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group()
        db.get.return_value = mock_group

        result = GroupService.get_group(db, DEFAULT_ID)
        assert result == mock_group

    def test_update_group_success(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=DEFAULT_ID)
        current_user = make_mock_user(role="admin")
        data = GroupUpdate(name="Renamed Group")

        result = GroupService.update_group(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_group_not_found(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = GroupUpdate(name="Renamed Group")

        with pytest.raises(NotFoundError):
            GroupService.update_group(db, MISSING_ID, data, current_user)

    def test_update_group_forbidden(self):
        from app.schema.talent import GroupUpdate
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = GroupUpdate(name="Renamed Group")

        with pytest.raises(ForbiddenError):
            GroupService.update_group(db, DEFAULT_ID, data, current_user)

    def test_delete_group_success(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=True)
        db.get.return_value = mock_group
        current_user = make_mock_user(role="admin")

        result = GroupService.delete_group(db, DEFAULT_ID, current_user)
        assert result is mock_group
        assert mock_group.is_active is False
        db.commit.assert_called_once()
        db.delete.assert_not_called()  # soft delete, not a hard db.delete()

    def test_delete_group_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GroupService.delete_group(db, MISSING_ID, current_user)

    def test_delete_group_forbidden(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.delete_group(db, DEFAULT_ID, current_user)

    def test_reactivate_group_success(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.return_value = mock_group
        current_user = make_mock_user(role="admin")

        result = GroupService.reactivate_group(db, DEFAULT_ID, current_user)
        assert mock_group.is_active is True
        db.commit.assert_called_once()
        assert result is not None

    def test_reactivate_group_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GroupService.reactivate_group(db, MISSING_ID, current_user)

    def test_reactivate_group_forbidden(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GroupService.reactivate_group(db, DEFAULT_ID, current_user)

    def test_get_groups_page_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group()
        db.query().filter().all.return_value = [mock_group]
        db.query().filter().group_by().all.return_value = [(mock_group.id, 3)]

        result = GroupService.get_groups_page(db)
        assert len(result.groups) == 1
        assert result.groups[0].id == mock_group.id
        assert mock_group.member_count == 3

    def test_get_groups_page_empty(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GroupService.get_groups_page(db)
        assert result is None

    def test_get_group_detail_found(self):
        from app.schema.marketplace import ArtistRef, ProductCard
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        mock_group = make_mock_group(is_active=True)
        mock_idol = make_mock_idol()
        mock_concert = make_mock_concert()
        mock_product = MagicMock()
        db.get.return_value = mock_group
        db.query().options().filter().all.return_value = [mock_idol]  # members
        db.query().join().filter().options().distinct().order_by().all.return_value = [mock_concert]  # events
        db.query().options().all.return_value = [mock_product]  # all_products

        mock_card = ProductCard(
            id=DEFAULT_ID, name="Hoodie", price=10.0, description="d", quantity=1,
            category="Merch", artist=ArtistRef(type="group", id=DEFAULT_ID, name="Prism"),
        )
        with patch(
            "app.services.marketplace.product_service.ProductService._build_product_cards",
            return_value=[mock_card],
        ):
            result = GroupService.get_group_detail(db, DEFAULT_ID)

        assert result.group.id == mock_group.id
        assert len(result.members) == 1
        assert result.members[0].id == mock_idol.id
        assert len(result.events) == 1
        assert result.events[0].id == mock_concert.id
        assert len(result.products) == 1

    def test_get_group_detail_not_found(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = None

        result = GroupService.get_group_detail(db, MISSING_ID)
        assert result is None

    def test_get_group_detail_inactive(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.get.return_value = make_mock_group(is_active=False)

        result = GroupService.get_group_detail(db, DEFAULT_ID)
        assert result is None

    def test_get_manager_groups_page(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().all.return_value = [make_mock_group()]

        result = GroupService.get_manager_groups_page(db)
        assert len(result.groups) == 1

    def test_get_manager_groups_page_empty_is_not_404(self):
        from app.services.talent.group_service import GroupService

        db = MagicMock()
        db.query().all.return_value = []

        # Manager/admin settings pages deliberately never sentinel-False on
        # empty — a fresh company legitimately has zero groups.
        result = GroupService.get_manager_groups_page(db)
        assert result.groups == []
