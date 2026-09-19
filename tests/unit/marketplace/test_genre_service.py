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
# Marketplace domain: Genre Service Tests
# ───────────────────────────────────────────────────────────────

class TestGenreService:

    def test_add_genre_success(self):
        from app.schema.marketplace import GenreCreate
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        data = GenreCreate(name="City Pop")

        result = GenreService.add_genre(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = GenreService.get_genres(db)
        assert len(result) == 1

    def test_get_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = []

        result = GenreService.get_genres(db)
        assert result is False

    def test_delete_genre_success(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_genre = MagicMock()
        db.get.return_value = mock_genre

        result = GenreService.delete_genre(db, DEFAULT_ID)
        db.delete.assert_called_once_with(mock_genre)
        db.commit.assert_called_once()
        assert result is True

    def test_delete_genre_not_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.return_value = None

        result = GenreService.delete_genre(db, MISSING_ID)
        assert result is False

    def test_assign_genre_success(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock(), AlbumGenre: None,
        })
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        result = GenreService.assign_genre(db, data, current_user)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_assign_genre_album_not_found(self):
        from app.db.models.marketplace import AlbumDetail
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumDetail: None})
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=MISSING_ID, genre_id=DEFAULT_ID)

        with pytest.raises(NotFoundError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_genre_not_found(self):
        from app.db.models.marketplace import AlbumDetail, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol, Genre: None})
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=MISSING_ID)

        with pytest.raises(NotFoundError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock()})
        current_user = make_mock_manager(company_id=DEFAULT_ID)
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GenreService.assign_genre(db, data, current_user)

    def test_assign_genre_conflict(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre, Genre
        from app.db.models.talent import Idol
        from app.schema.marketplace import AlbumGenreAssign
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumDetail: mock_album, Idol: mock_idol, Genre: MagicMock(), AlbumGenre: MagicMock(),
        })
        current_user = make_mock_user(role="admin")
        data = AlbumGenreAssign(product_id=DEFAULT_ID, genre_id=DEFAULT_ID)

        with pytest.raises(BadRequestError):
            GenreService.assign_genre(db, data, current_user)

    def test_get_album_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().filter().all.return_value = [MagicMock()]

        result = GenreService.get_album_genres(db, DEFAULT_ID)
        assert len(result) == 1

    def test_get_album_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = GenreService.get_album_genres(db, DEFAULT_ID)
        assert result is False

    def test_get_all_album_genres_found(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = [MagicMock(), MagicMock()]

        result = GenreService.get_all_album_genres(db)
        assert len(result) == 2

    def test_get_all_album_genres_empty(self):
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.query().all.return_value = []

        result = GenreService.get_all_album_genres(db)
        assert result is False

    def test_remove_genre_success(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre
        from app.db.models.talent import Idol
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        link = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=DEFAULT_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumGenre: link, AlbumDetail: mock_album, Idol: mock_idol,
        })
        current_user = make_mock_user(role="admin")

        result = GenreService.remove_genre(db, DEFAULT_ID, DEFAULT_ID, current_user)
        assert result is link
        db.delete.assert_called_once_with(link)

    def test_remove_genre_not_found(self):
        from app.db.models.marketplace import AlbumGenre
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({AlbumGenre: None})
        current_user = make_mock_user(role="admin")

        with pytest.raises(NotFoundError):
            GenreService.remove_genre(db, MISSING_ID, MISSING_ID, current_user)

    def test_remove_genre_forbidden(self):
        from app.db.models.marketplace import AlbumDetail, AlbumGenre
        from app.db.models.talent import Idol
        from app.services.marketplace.genre_service import GenreService

        db = MagicMock()
        link = MagicMock()
        mock_album = MagicMock(idol_id=DEFAULT_ID, group_id=None)
        mock_idol = make_mock_idol(company_id=OTHER_ID)
        db.get.side_effect = model_get_side_effect({
            AlbumGenre: link, AlbumDetail: mock_album, Idol: mock_idol,
        })
        current_user = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            GenreService.remove_genre(db, DEFAULT_ID, DEFAULT_ID, current_user)
