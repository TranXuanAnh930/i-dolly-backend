from datetime import datetime
from pydantic import BaseModel, Field

class TicketTypeBase(BaseModel):
    tier: str  # 'vip' | 'premium' | 'regular'
    price: float = Field(..., ge=0)
    total_quantity: int = Field(..., ge=0)
    sale_method: str = "lottery"  # 'lottery' | 'direct'

class TicketTypeCreate(TicketTypeBase):
    concert_id: int

class TicketTypeUpdate(BaseModel):
    price: float | None = Field(None, ge=0)
    total_quantity: int | None = Field(None, ge=0)

class TicketTypeRead(TicketTypeBase):
    id: int
    concert_id: int
    sold_quantity: int
    created_at: datetime

    model_config = {"from_attributes": True}
