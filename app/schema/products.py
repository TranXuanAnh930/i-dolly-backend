import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field
from app.schema.genre import GenreRead
from app.schema.artist import ArtistRef
from app.schema.idol import GroupMini
from app.schema.category import CategoryRead
from app.schema.order import OrderStatus

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
