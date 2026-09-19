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

# Distinct from ProductRead — ProductRead.category is a resolved name (str), built by hand from
# the Category relationship. search_existing_product/paginated_product/filter_product return raw
# Product rows instead, so category here is the full CategoryRead object, validated directly.
class ProductWithCategoryRead(ProductBase):
    id: uuid.UUID
    category: CategoryRead

    model_config = {"from_attributes": True}

class ProductsPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[ProductWithCategoryRead]

# Bundles a Product with its AlbumDetail/MerchDetail row into one request, so a product is never
# left ownerless the way a bare add_product + optional follow-up call could leave it. detail_kind
# picks which set of fields below applies, mirroring AlbumDetailCreate/MerchDetailCreate's own
# idol_id/group_id validators.
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

# --- page-shaped reads. ProductCard is the shape every product-grid view renders (store grid, a
# group's products, recommendations) — album info, genres, and the resolved artist all embedded
# so the client never needs a second lookup.

class AlbumMini(BaseModel):
    release_date: date | None = None
    track_count: int | None = None
    cover_image_url: str | None = None

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
    # None = not resale-capped; otherwise the max units a fan may buy of
    # this product, cumulative across every order they've ever placed (see
    # order_service.checkout and app/utils/resale.RESALE_CAP_QUANTITY).
    resale_cap_quantity: int | None = None

# Deliberately not with the top imports, and a direct submodule import rather than the
# app.schema.talent package shortcut: talent needs marketplace back (group.py imports
# ProductCard), so a package-level import on either side of that cycle needs the other package's
# __init__ to have already finished — regardless of which side loads first.
from app.schema.talent.idol import GroupMini, GroupOptionForCompany, IdolRead  # noqa: E402
from app.schema.talent.idol_color import IdolColorRead  # noqa: E402


class StorePageRead(BaseModel):
    products: list[ProductCard]
    groups: list[GroupMini]  # for the store page's unit filter only

class ProductDetailRead(BaseModel):
    product: ProductCard
    recommendations: list[ProductCard]

# --- manager/admin settings pages — ManagerProductsPage's table only needs
# the plain product rows (no album/genre/artist embedding); the form page
# additionally needs the category list for its <select>. Neither needs
# album_details at all. An empty list here is a normal state, not a 404.

class ManagerProductsPageRead(BaseModel):
    products: list[ProductRead]

class ManagerProductFormPageRead(BaseModel):
    products: list[ProductRead]
    categories: list[CategoryRead]
    # For the "product for one of my own idols/groups" step of creating a
    # product — idols/groups carry company_id so the form can filter to the
    # current company client-side, same pattern as ManagerIdolFormPageRead's
    # own groups field. colors is only ever used for a merch product's
    # optional color_id.
    idols: list[IdolRead] = []
    groups: list[GroupOptionForCompany] = []
    colors: list[IdolColorRead] = []

# --- sales history (GET /products/{id}/sales) — one row per order that
# included this product, newest first. Same page/limit/count/data envelope
# as /products/pagination.

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
