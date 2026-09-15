import uuid
from datetime import date, datetime

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

# Bundles a Product with its AlbumDetail/MerchDetail row into one request
# (product_service.add_product_with_detail) — a bare add_product left a
# product with no album_details/merch_details row until a separate,
# optional follow-up call attached one; this is the route
# ManagerProductFormPage.vue now uses instead so a product is never left
# without one. detail_kind picks which set of the fields below applies —
# mirrors AlbumDetailCreate's "at least one of idol_id/group_id" and
# MerchDetailCreate's "exactly one" validators respectively.
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
    def _check_kind_and_owner(self):
        if self.detail_kind == "album":
            if self.idol_id is None and self.group_id is None:
                raise ValueError("At least one of idol_id or group_id must be set for an album/single/EP product")
        elif self.detail_kind == "merch":
            if (self.idol_id is None) == (self.group_id is None):
                raise ValueError("Exactly one of idol_id or group_id must be set for a merch product")
        else:
            raise ValueError("detail_kind must be 'album' or 'merch'")
        return self

# --- page-shaped reads — one bundled response per screen (see idol.py's
# equivalent comment). ProductCard is the single shape every product-grid
# view renders (store grid, a group's products, a product's own
# recommendations) — album info, genre tags, and the resolved artist
# (idol/group, from album_details/merch_details, or a name-prefix
# match for plain merch with neither) all embedded so the client never
# needs a second lookup to render one.

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

# Deliberately not up with the other imports at the top of this file, AND
# deliberately direct-submodule (not the app.schema.talent package shortcut):
# talent needs marketplace back (group.py imports ProductCard), so a
# package-level import on either side of that cycle needs the whole other
# package's __init__ to have finished first — true regardless of which side
# is entered first, confirmed by testing every domain as the first import in
# a fresh process, not just the one order that happened to work. Nothing
# above this line needs anything from talent; this is the first thing that
# does, so both imports only need to land before here, not at the top.
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
    price: int
    line_total: int

class ProductSalesPageRead(BaseModel):
    page: int
    limit: int
    count: int
    data: list[ProductSaleRead]
