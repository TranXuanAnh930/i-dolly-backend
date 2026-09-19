import uuid
from datetime import datetime, timedelta, timezone
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

NOW = datetime.now(timezone.utc)

# ───────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────

def make_mock_manager(company_id=DEFAULT_ID):
    manager = MagicMock()
    manager.role = "manager"
    manager.company_id = company_id
    return manager

def make_mock_admin():
    admin = MagicMock()
    admin.role = "admin"
    admin.company_id = None
    return admin

def make_mock_concert(id=DEFAULT_ID, company_id=DEFAULT_ID):
    concert = MagicMock()
    concert.id = id
    concert.company_id = company_id
    return concert

def make_mock_ticket_type(id=DEFAULT_ID, concert_id=DEFAULT_ID, sale_method="direct"):
    tt = MagicMock()
    tt.id = id
    tt.concert_id = concert_id
    tt.sale_method = sale_method
    return tt

def make_mock_campaign(id=DEFAULT_ID, ticket_type_id=DEFAULT_ID, status="open"):
    campaign = MagicMock()
    campaign.id = id
    campaign.ticket_type_id = ticket_type_id
    campaign.status = status
    campaign.sale_start_at = NOW - timedelta(days=1)
    campaign.sale_end_at = NOW + timedelta(days=30)
    return campaign

def model_get_side_effect(mapping: dict):
    def _side_effect(model, ident=None):
        return mapping.get(model)
    return _side_effect

# ───────────────────────────────────────────────────────────────
# Direct Sale Campaign Service Tests
# ───────────────────────────────────────────────────────────────

class TestDirectSaleCampaignService:

    def test_add_campaign_success(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import DirectSaleCampaignCreate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            TicketType: make_mock_ticket_type(sale_method="direct"),
            Concert: make_mock_concert(),
        })
        data = DirectSaleCampaignCreate(
            ticket_type_id=DEFAULT_ID,
            sale_start_at=NOW - timedelta(days=1), sale_end_at=NOW + timedelta(days=30),
        )
        manager = make_mock_manager(company_id=DEFAULT_ID)

        result = DirectSaleCampaignService.add_campaign(db, data, manager)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        assert result is not None

    def test_add_campaign_ticket_type_not_found(self):
        from app.db.models.events import TicketType
        from app.schema.events import DirectSaleCampaignCreate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({TicketType: None})
        data = DirectSaleCampaignCreate(
            ticket_type_id=MISSING_ID,
            sale_start_at=NOW - timedelta(days=1), sale_end_at=NOW + timedelta(days=30),
        )

        with pytest.raises(NotFoundError):
            DirectSaleCampaignService.add_campaign(db, data, make_mock_admin())

    def test_add_campaign_rejects_lottery_ticket_type(self):
        from app.db.models.events import TicketType
        from app.schema.events import DirectSaleCampaignCreate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({TicketType: make_mock_ticket_type(sale_method="lottery")})
        data = DirectSaleCampaignCreate(
            ticket_type_id=DEFAULT_ID,
            sale_start_at=NOW - timedelta(days=1), sale_end_at=NOW + timedelta(days=30),
        )

        with pytest.raises(BadRequestError):
            DirectSaleCampaignService.add_campaign(db, data, make_mock_admin())

    def test_add_campaign_manager_wrong_company_forbidden(self):
        from app.db.models.events import Concert, TicketType
        from app.schema.events import DirectSaleCampaignCreate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.side_effect = model_get_side_effect({
            TicketType: make_mock_ticket_type(sale_method="direct"),
            Concert: make_mock_concert(company_id=OTHER_ID),
        })
        data = DirectSaleCampaignCreate(
            ticket_type_id=DEFAULT_ID,
            sale_start_at=NOW - timedelta(days=1), sale_end_at=NOW + timedelta(days=30),
        )
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            DirectSaleCampaignService.add_campaign(db, data, manager)

    def test_get_campaigns_found(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.query().filter().all.return_value = [make_mock_campaign()]

        result = DirectSaleCampaignService.get_campaigns(db, DEFAULT_ID)
        assert result is not None

    def test_get_campaigns_empty(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.query().filter().all.return_value = []

        result = DirectSaleCampaignService.get_campaigns(db, MISSING_ID)
        assert result is None

    def test_get_campaign_found(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.return_value = make_mock_campaign()

        result = DirectSaleCampaignService.get_campaign(db, DEFAULT_ID)
        assert result is not None

    def test_get_campaign_not_found(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.return_value = None

        result = DirectSaleCampaignService.get_campaign(db, MISSING_ID)
        assert result is None

    def test_update_campaign_not_found(self):
        from app.schema.events import DirectSaleCampaignUpdate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.return_value = None
        data = DirectSaleCampaignUpdate(sale_start_at=NOW, sale_end_at=NOW + timedelta(days=1))

        with pytest.raises(NotFoundError):
            DirectSaleCampaignService.update_campaign(db, MISSING_ID, data, make_mock_admin())

    def test_update_campaign_manager_wrong_company_forbidden(self):
        from app.schema.events import DirectSaleCampaignUpdate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        campaign = make_mock_campaign()
        db = MagicMock()
        db.get.side_effect = [campaign, make_mock_ticket_type(), make_mock_concert(company_id=OTHER_ID)]
        data = DirectSaleCampaignUpdate(sale_start_at=NOW, sale_end_at=NOW + timedelta(days=1))
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            DirectSaleCampaignService.update_campaign(db, DEFAULT_ID, data, manager)

    def test_update_campaign_success(self):
        from app.schema.events import DirectSaleCampaignUpdate
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        campaign = make_mock_campaign()
        db = MagicMock()
        db.get.side_effect = [campaign, make_mock_ticket_type(), make_mock_concert()]
        new_start = NOW - timedelta(hours=1)
        new_end = NOW + timedelta(days=60)
        data = DirectSaleCampaignUpdate(sale_start_at=new_start, sale_end_at=new_end, status="cancelled")

        result = DirectSaleCampaignService.update_campaign(db, DEFAULT_ID, data, make_mock_admin())

        assert result.sale_start_at == new_start
        assert result.sale_end_at == new_end
        assert result.status == "cancelled"
        db.commit.assert_called_once()

    def test_delete_campaign_not_found(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(NotFoundError):
            DirectSaleCampaignService.delete_campaign(db, MISSING_ID, make_mock_admin())

    def test_delete_campaign_manager_wrong_company_forbidden(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        campaign = make_mock_campaign()
        db = MagicMock()
        db.get.side_effect = [campaign, make_mock_ticket_type(), make_mock_concert(company_id=OTHER_ID)]
        manager = make_mock_manager(company_id=DEFAULT_ID)

        with pytest.raises(ForbiddenError):
            DirectSaleCampaignService.delete_campaign(db, DEFAULT_ID, manager)

    def test_delete_campaign_success(self):
        from app.services.events.direct_sale_campaign_service import DirectSaleCampaignService

        campaign = make_mock_campaign()
        db = MagicMock()
        db.get.side_effect = [campaign, make_mock_ticket_type(), make_mock_concert()]

        result = DirectSaleCampaignService.delete_campaign(db, DEFAULT_ID, make_mock_admin())

        assert result == campaign
        db.delete.assert_called_once_with(campaign)
        db.commit.assert_called_once()
