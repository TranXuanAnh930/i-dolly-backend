import uuid
from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.schema.marketplace.artist import ArtistRef
from app.schema.marketplace.category import CategoryRead
from app.schema.marketplace.genre import GenreRead
from app.schema.marketplace.order import OrderStatus


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=1000)
    quantity: int = Field(..., ge=0)
    image_url: str | None = None

class ProductUpdate(ProductBase):
    id : uuid.UUID

class ProductCreate(ProductBase):
    category_id : uuid.UUID

class ProductRead(ProductBase):
    id: uuid.UUID
    category : str

# Product with its full CategoryRead (ProductRead has only the category name).
class ProductWithCategoryRead(ProductBase):
    id: uuid.UUID
    category: CategoryRead

    model_config = {"from_attributes": True}

class ProductsPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[ProductWithCategoryRead]

# Creates a product together with its AlbumDetail or MerchDetail row. detail_kind selects which
# fields below apply.
class ProductWithDetailCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=1000)
    quantity: int = Field(..., ge=0)
    category_id: uuid.UUID
    detail_kind: str  # 'album' | 'merch'
    idol_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    # album-only (detail_kind == 'album')
    release_date: date | None = None
    track_count: int | None = Field(None, gt=0)
    format: str = "physical"
    # merch-only (detail_kind == 'merch')
    edition: str | None = None
    color_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_kind_and_owner(self) -> Self:
        if self.detail_kind == "album":
            if self.idol_id is None and self.group_id is None:
                raise ValueError("At least one of idol_id or group_id must be set for an album/single/EP product")
        elif self.detail_kind == "merch":
            if (self.idol_id is None) == (self.group_id is None):
                raise ValueError("Exactly one of idol_id or group_id must be set for a merch product")
        else:
            raise ValueError("detail_kind must be 'album' or 'merch'")
        return self

# --- page-shaped reads. ProductCard is the shape every product grid renders, with album info,
# genres and the resolved artist embedded.

class AlbumMini(BaseModel):
    release_date: date | None = None
    track_count: int | None = None

class ProductCard(BaseModel):
    id: uuid.UUID
    name: str
    price: float
    description: str
    quantity: int
    image_url: str | None = None
    category: str
    album: AlbumMini | None = None
    genres: list[GenreRead] = []
    artist: ArtistRef | None = None
    # Max units a fan may buy across all their orders; None if the product isn't resale-capped.
    resale_cap_quantity: int | None = None

# Imported here, from the submodule, to break the talent <-> marketplace schema import cycle.
from app.schema.talent.idol import GroupMini, GroupOptionForCompany, IdolRead  # noqa: E402
from app.schema.talent.idol_color import IdolColorRead  # noqa: E402


class StorePageRead(BaseModel):
    products: list[ProductCard]
    groups: list[GroupMini]  # for the store page's group filter

class ProductDetailRead(BaseModel):
    product: ProductCard
    recommendations: list[ProductCard]

# --- manager/admin settings pages (an empty list is a normal result, not a 404).

class ManagerProductsPageRead(BaseModel):
    products: list[ProductRead]

class ManagerProductFormPageRead(BaseModel):
    products: list[ProductRead]
    categories: list[CategoryRead]
    # Idols/groups to attach a new product to (filtered by company client-side); colors are for
    # merch products.
    idols: list[IdolRead] = []
    groups: list[GroupOptionForCompany] = []
    colors: list[IdolColorRead] = []

# --- sales history (GET /products/{id}/sales): one row per order containing the product,
# newest first.

class ProductSaleRead(BaseModel):
    order_id: uuid.UUID
    order_status: OrderStatus
    order_created_at: datetime
    quantity: int
    price: float
    line_total: float

class ProductSalesPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[ProductSaleRead]
