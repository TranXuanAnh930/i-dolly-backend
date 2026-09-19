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
# Venue Service Tests
# ───────────────────────────────────────────────────────────────

class TestVenueService:

    def test_add_venue_success(self):
        from app.schema.events import VenueCreate
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        data = VenueCreate(name="Arena", address="1 Main St", city="Tokyo", country="Japan", total_capacity=5000)

        result = VenueService.add_venue(db, data)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_venues_found(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.query().all.return_value = [MagicMock()]

        result = VenueService.get_venues(db)
        assert result is not None

    def test_get_venues_empty(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.query().all.return_value = []

        result = VenueService.get_venues(db)
        assert result == []

    def test_get_venue_found(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.get.return_value = MagicMock()

        result = VenueService.get_venue(db, DEFAULT_ID)
        assert result is not None

    def test_get_venue_not_found(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.get.return_value = None

        result = VenueService.get_venue(db, MISSING_ID)
        assert result is None

    def test_update_venue_success(self):
        from app.schema.events import VenueUpdate
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        mock_venue = MagicMock()
        db.get.return_value = mock_venue
        data = VenueUpdate(
            name="Renamed Arena", address="2 Main St", city="Osaka",
            country="Japan", total_capacity=8000, contact_info="info@venue.example",
        )

        result = VenueService.update_venue(db, DEFAULT_ID, data)

        assert result.name == "Renamed Arena"
        assert result.total_capacity == 8000
        db.commit.assert_called_once()

    def test_update_venue_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.events import VenueUpdate
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.get.return_value = None
        data = VenueUpdate(
            name="Renamed Arena", address="2 Main St", city="Osaka",
            country="Japan", total_capacity=8000,
        )

        with pytest.raises(NotFoundError):
            VenueService.update_venue(db, MISSING_ID, data)

    def test_delete_venue_success(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        mock_venue = MagicMock()
        db.get.return_value = mock_venue

        result = VenueService.delete_venue(db, DEFAULT_ID)
        assert result is True
        db.delete.assert_called_once_with(mock_venue)
        db.commit.assert_called_once()

    def test_delete_venue_not_found(self):
        from app.services.events.venue_service import VenueService

        db = MagicMock()
        db.get.return_value = None

        result = VenueService.delete_venue(db, MISSING_ID)
        assert result is False
