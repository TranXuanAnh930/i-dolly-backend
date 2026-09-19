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
# Position Service Tests
# ───────────────────────────────────────────────────────────────

class TestPositionService:

    def test_add_position_success(self):
        from app.schema.talent import PositionCreate
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        data = PositionCreate(name="Center")

        result = PositionService.add_position(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = PositionService.get_positions(db)
        assert len(result) == 1

    def test_get_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = []

        result = PositionService.get_positions(db)
        assert result == []

    def test_update_position_success(self):
        from app.schema.talent import PositionBase
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = MagicMock()
        data = PositionBase(name="Leader")

        result = PositionService.update_position(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not None

    def test_update_position_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.talent import PositionBase
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        data = PositionBase(name="Leader")

        with pytest.raises(NotFoundError):
            PositionService.update_position(db, MISSING_ID, data)

    def test_delete_position_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = MagicMock()

        result = PositionService.delete_position(db, DEFAULT_ID)
        db.delete.assert_called_once()
        db.commit.assert_called_once()
        assert result is True

    def test_delete_position_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None

        result = PositionService.delete_position(db, MISSING_ID)
        assert result is False

    # --- idol_positions join table ---

    def test_assign_idol_position_success(self):
        from app.db.models.talent import Idol, IdolPosition, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        mock_position = MagicMock()
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, Position: mock_position, IdolPosition: None})
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID, is_primary=True)

        result = PositionService.assign_idol_position(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_assign_idol_position_idol_or_position_not_found(self):
        from app.db.models.talent import Idol, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({Idol: None, Position: MagicMock()})
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=MISSING_ID, position_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_assign_idol_position_forbidden(self):
        from app.db.models.talent import Idol, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({Idol: mock_idol, Position: MagicMock()})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_assign_idol_position_conflict(self):
        from app.db.models.talent import Idol, IdolPosition, Position
        from app.schema.talent import IdolPositionAssign
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            Idol: mock_idol, Position: MagicMock(), IdolPosition: MagicMock(),
        })
        current_user = make_mock_user(role="admin")
        data = IdolPositionAssign(idol_id=DEFAULT_ID, position_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            PositionService.assign_idol_position(db, data, current_user)

    def test_get_idol_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = PositionService.get_idol_positions(db, DEFAULT_ID)
        assert len(result) == 1

    def test_get_idol_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = PositionService.get_idol_positions(db, DEFAULT_ID)
        assert result == []

    def test_get_all_idol_positions_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(), MagicMock()]

        result = PositionService.get_all_idol_positions(db)
        assert len(result) == 2

    def test_get_all_idol_positions_empty(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.query().all.return_value = []

        result = PositionService.get_all_idol_positions(db)
        assert result == []

    def test_update_idol_position_primary_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = DEFAULT_ID
        db.get.return_value = link
        current_user = make_mock_user(role="admin")

        result = PositionService.update_idol_position_primary(db, DEFAULT_ID, DEFAULT_ID, True, current_user)
        assert result == link
        assert link.is_primary is True
        db.commit.assert_called_once()

    def test_update_idol_position_primary_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            PositionService.update_idol_position_primary(db, MISSING_ID, MISSING_ID, True, current_user)

    def test_update_idol_position_primary_forbidden(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = OTHER_ID
        db.get.return_value = link
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.update_idol_position_primary(db, DEFAULT_ID, DEFAULT_ID, True, current_user)

    def test_remove_idol_position_success(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = DEFAULT_ID
        db.get.return_value = link
        current_user = make_mock_user(role="admin")

        result = PositionService.remove_idol_position(db, DEFAULT_ID, DEFAULT_ID, current_user)
        db.delete.assert_called_once_with(link)
        db.commit.assert_called_once()
        assert result is link

    def test_remove_idol_position_not_found(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        db.get.return_value = None
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            PositionService.remove_idol_position(db, MISSING_ID, MISSING_ID, current_user)

    def test_remove_idol_position_forbidden(self):
        from app.services.talent.position_service import PositionService

        db = MagicMock()
        link = MagicMock()
        link.idol.company_id = OTHER_ID
        db.get.return_value = link
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            PositionService.remove_idol_position(db, DEFAULT_ID, DEFAULT_ID, current_user)
