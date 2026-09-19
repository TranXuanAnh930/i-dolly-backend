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
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_company(id=DEFAULT_ID, name="Nova Entertainment"):
    company = MagicMock()
    company.id = id
    company.name = name
    return company


# ───────────────────────────────────────────────────────────────
# Management Company Service Tests
# ───────────────────────────────────────────────────────────────

class TestManagementCompanyService:

    def test_add_company_success(self):
        from app.schema.talent import ManagementCompanyCreate
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        data = ManagementCompanyCreate(name="Nova Entertainment")

        result = ManagementCompanyService.add_company(db, data)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_get_companies_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.query().all.return_value = [make_mock_company()]

        result = ManagementCompanyService.get_companies(db)
        assert len(result) == 1

    def test_get_companies_empty(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.query().all.return_value = []

        result = ManagementCompanyService.get_companies(db)
        assert result == []

    def test_get_company_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        mock_company = make_mock_company()
        db.get.return_value = mock_company

        result = ManagementCompanyService.get_company(db, DEFAULT_ID)
        assert result == mock_company

    def test_get_company_not_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None

        result = ManagementCompanyService.get_company(db, MISSING_ID)
        assert result is None

    def test_update_company_success(self):
        from app.schema.talent import ManagementCompanyBase
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = make_mock_company()
        data = ManagementCompanyBase(name="Renamed", description="New desc", contact_email="a@b.com")

        result = ManagementCompanyService.update_company(db, DEFAULT_ID, data)
        db.commit.assert_called_once()
        assert result is not None
        assert result.name == "Renamed"

    def test_update_company_not_found(self):
        from app.exception.common import NotFoundError
        from app.schema.talent import ManagementCompanyBase
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None
        data = ManagementCompanyBase(name="Renamed")

        with pytest.raises(NotFoundError):
            ManagementCompanyService.update_company(db, MISSING_ID, data)

    def test_delete_company_success(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        mock_company = make_mock_company()
        db.get.return_value = mock_company

        result = ManagementCompanyService.delete_company(db, DEFAULT_ID)
        db.delete.assert_called_once_with(mock_company)
        db.commit.assert_called_once()
        assert result is True

    def test_delete_company_not_found(self):
        from app.services.talent.management_company_service import ManagementCompanyService

        db = MagicMock()
        db.get.return_value = None

        result = ManagementCompanyService.delete_company(db, MISSING_ID)
        assert result is False
