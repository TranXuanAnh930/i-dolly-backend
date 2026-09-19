import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, model_validator


class DirectSaleCampaignBase(BaseModel):
    sale_start_at: datetime
    sale_end_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.sale_end_at <= self.sale_start_at:
            raise ValueError("sale_end_at must be after sale_start_at")
        return self

class DirectSaleCampaignCreate(DirectSaleCampaignBase):
    ticket_type_id: uuid.UUID

class DirectSaleCampaignUpdate(DirectSaleCampaignBase):
    status: str | None = None  # 'open' | 'cancelled'

class DirectSaleCampaignRead(DirectSaleCampaignBase):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
