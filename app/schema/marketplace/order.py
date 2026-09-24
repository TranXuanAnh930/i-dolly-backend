import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from app.schema.marketplace.shipping import ShippingAddress, ShippingStatusResponse


class OrderStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"

class OrderItem(BaseModel):
    order_id : uuid.UUID
    product_id : uuid.UUID
    quantity : int
    price : float

    model_config = {"from_attributes" : True}

class Order(BaseModel):
    id : uuid.UUID
    user_id : uuid.UUID
    shipping_address_id :uuid.UUID
    total_price : float
    status : OrderStatus
    created_at : datetime
    items : list[OrderItem]
    shippingstatus : ShippingStatusResponse
    shippingaddress : ShippingAddress

    model_config = {"from_attributes" : True}

# --- manager/admin orders page (GET /order/manager-orders-page) — one row
# per order that included at least one of the company's products, newest
# first, with `items` narrowed to just that company's line items (not the
# whole order — a manager shouldn't see what a customer also bought from
# another company in the same checkout). Same page/limit/count/data
# envelope as /products/pagination.

class ManagerOrderItemRead(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    price: float

class ManagerOrderRead(BaseModel):
    id: uuid.UUID
    buyer_name: str
    buyer_email: str
    status: OrderStatus
    created_at: datetime
    items: list[ManagerOrderItemRead]
    company_total: float
    # None only for a pre-existing order somehow missing its ShippingStatus
    # row (every new order gets one at checkout) — lets the manager UI's
    # "Ship" button gate on it without assuming it's always present, same
    # defensiveness as OrderService.ship_order's own check.
    shippingstatus: ShippingStatusResponse | None

class ManagerOrdersPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[ManagerOrderRead]