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

def make_mock_color(id=DEFAULT_ID, name="Crimson", hex_code="#FF0000"):
    color = MagicMock()
    color.id = id
    color.name = name
    color.hex_code = hex_code
    return color

def model_get_side_effect(mapping: dict):
    """Builds a db.get(Model, id) side_effect that dispatches on the model
    class, since a plain MagicMock().get ignores call args and can't tell
    db.get(Product, ...) apart from db.get(AlbumDetail, ...) on its own."""
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect


# ───────────────────────────────────────────────────────────────
# Talent domain: Idol Service Tests
# ───────────────────────────────────────────────────────────────

class TestIdolService:

    def test_add_idol_success(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID)

        result = IdolService.add_idol(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_idol_forbidden(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        current_user = make_mock_manager(company_id=OTHER_ID)
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.add_idol(db, data, current_user)
        db.add.assert_not_called()

    def test_add_idol_company_not_found(self):
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_group_not_found(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: None})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_color_not_found(self):
        from app.db.models.talent import IdolColor, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), IdolColor: None})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, color_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_company_mismatch(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mismatched_group = make_mock_group(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: mismatched_group})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=OTHER_ID)

        with pytest.raises(BadRequestError):
            IdolService.add_idol(db, data, current_user)

    def test_add_idol_group_inactive(self):
        from app.db.models.talent import Group, ManagementCompany
        from app.schema.talent import IdolCreate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({ManagementCompany: make_mock_company(), Group: inactive_group})
        current_user = make_mock_user(role="admin")
        data = IdolCreate(name="Yuki", company_id=DEFAULT_ID, group_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            IdolService.add_idol(db, data, current_user)

    def test_get_idols_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_idol()]

        result = IdolService.get_idols(db)
        assert len(result) == 1

    def test_get_idols_empty(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = IdolService.get_idols(db)
        assert result is False

    def test_get_idol(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol()
        db.get.return_value = mock_idol

        result = IdolService.get_idol(db, DEFAULT_ID)
        assert result == mock_idol

    def test_update_idol_success(self):
        from app.db.models.talent import Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=None)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, ManagementCompany: make_mock_company()})
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol")

        result = IdolService.update_idol(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_idol_not_found(self):
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol")

        with pytest.raises(NotFoundError):
            IdolService.update_idol(db, MISSING_ID, data, current_user)

    def test_update_idol_forbidden(self):
        from app.db.models.talent import Idol
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = IdolUpdate(name="Renamed Idol")

        with pytest.raises(ForbiddenError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_company_mismatch(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=None)
        mismatched_group = make_mock_group(company_id=OTHER_ID, is_active=True)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: mismatched_group,
        })
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol", group_id=OTHER_ID)

        with pytest.raises(BadRequestError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_group_inactive_blocks_new_assignment(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        new_group_id = uuid.uuid4()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=OTHER_ID)  # currently in OTHER_ID
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: inactive_group,
        })
        current_user = make_mock_user(role="admin")
        data = IdolUpdate(name="Renamed Idol", group_id=new_group_id)  # moving INTO a deactivated group

        with pytest.raises(BadRequestError):
            IdolService.update_idol(db, DEFAULT_ID, data, current_user)

    def test_update_idol_group_inactive_allows_unchanged_group(self):
        from app.db.models.talent import Group, Idol, ManagementCompany
        from app.schema.talent import IdolUpdate
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        same_group_id = uuid.uuid4()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, group_id=same_group_id)
        inactive_group = make_mock_group(company_id=DEFAULT_ID, is_active=False)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, ManagementCompany: make_mock_company(), Group: inactive_group,
        })
        current_user = make_mock_user(role="admin")
        # Full-replace PUT resending the idol's existing (now-deactivated) group_id
        # unchanged — not a new assignment, must not be blocked.
        data = IdolUpdate(name="Renamed Idol", group_id=same_group_id)

        result = IdolService.update_idol(db, DEFAULT_ID, data, current_user)
        db.commit.assert_called_once()
        assert result is not None

    def test_delete_idol_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=True)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        result = IdolService.delete_idol(db, DEFAULT_ID, current_user)
        assert result is mock_idol
        assert mock_idol.is_active is False
        db.delete.assert_not_called()  # soft delete

    def test_delete_idol_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.delete_idol(db, MISSING_ID, current_user)

    def test_delete_idol_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.delete_idol(db, DEFAULT_ID, current_user)

    def test_reactivate_idol_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID, is_active=False)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        result = IdolService.reactivate_idol(db, DEFAULT_ID, current_user)
        assert mock_idol.is_active is True
        assert result is not None

    def test_reactivate_idol_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.reactivate_idol(db, MISSING_ID, current_user)

    def test_reactivate_idol_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.reactivate_idol(db, DEFAULT_ID, current_user)

    def test_set_idol_image_success(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.return_value = mock_idol
        current_user = make_mock_user(role="admin")

        IdolService.set_idol_image(db, DEFAULT_ID, "https://cdn.example.com/idol.png", current_user)
        assert mock_idol.profile_image_url == "https://cdn.example.com/idol.png"
        db.commit.assert_called_once()

    def test_set_idol_image_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            IdolService.set_idol_image(db, MISSING_ID, "https://cdn.example.com/idol.png", current_user)

    def test_set_idol_image_forbidden(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.get.return_value = make_mock_idol(company_id=OTHER_ID)
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            IdolService.set_idol_image(db, DEFAULT_ID, "https://cdn.example.com/idol.png", current_user)

    def test_get_members_page_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().all.return_value = [make_mock_idol()]
        db.query().filter().all.return_value = [make_mock_group()]

        result = IdolService.get_members_page(db)
        assert len(result.idols) == 1
        assert len(result.groups) == 1

    def test_get_members_page_empty(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().all.return_value = []

        result = IdolService.get_members_page(db)
        assert result is False

    def test_get_idol_detail_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(group_id=OTHER_ID)
        mock_group = make_mock_group(id=OTHER_ID)
        sibling = make_mock_idol(id=uuid.uuid4(), group_id=OTHER_ID)
        db.query().options().filter().first.return_value = mock_idol
        db.get.return_value = mock_group
        db.query().filter().filter().options().all.return_value = [sibling]

        result = IdolService.get_idol_detail(db, DEFAULT_ID)
        assert result.idol.id == mock_idol.id
        assert result.group.id == mock_group.id
        assert len(result.siblings) == 1
        assert result.siblings[0].id == sibling.id

    def test_get_idol_detail_not_found(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        db.query().options().filter().first.return_value = None

        result = IdolService.get_idol_detail(db, MISSING_ID)
        assert result is False

    def test_get_idol_detail_no_group_solo_idol(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        mock_idol = make_mock_idol(group_id=None)
        db.query().options().filter().first.return_value = mock_idol
        db.query().filter().filter().options().all.return_value = []

        result = IdolService.get_idol_detail(db, DEFAULT_ID)
        assert result.idol.id == mock_idol.id
        assert result.group is None
        db.get.assert_not_called()  # no group_id -> no Group lookup at all

    def test_get_manager_idols_page(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        idols = [make_mock_idol()]
        groups = [make_mock_group()]
        db.query().all.side_effect = [idols, groups]

        result = IdolService.get_manager_idols_page(db)
        assert len(result.idols) == 1
        assert result.idols[0].id == idols[0].id
        assert len(result.groups) == 1
        assert result.groups[0].id == groups[0].id

    def test_get_manager_idol_form_page(self):
        from app.services.talent.idol_service import IdolService

        db = MagicMock()
        idols = [make_mock_idol()]
        groups = [make_mock_group()]
        colors = [make_mock_color()]
        db.query().all.side_effect = [idols, groups, colors]

        result = IdolService.get_manager_idol_form_page(db)
        assert len(result.idols) == 1
        assert len(result.groups) == 1
        assert len(result.colors) == 1
        assert result.colors[0].id == colors[0].id
