"""Re-exports every public schema class in this domain, so callers can do `from app.schema.marketplace import X` instead of reaching into the individual submodule."""

from .album_detail import AlbumDetailBase, AlbumDetailCreate, AlbumDetailRead, AlbumDetailUpdate
from .artist import ArtistRef
from .cart import CartItem, CartOut, CartRead
from .category import CategoryBase, CategoryCreate, CategoryRead, CategoryUpdate
from .genre import AlbumGenreAssign, AlbumGenreRead, GenreBase, GenreCreate, GenreRead
from .merch_detail import MerchDetailBase, MerchDetailCreate, MerchDetailRead, MerchDetailUpdate
from .order import ManagerOrderItemRead, ManagerOrderRead, ManagerOrdersPageRead, Order, OrderItem, OrderStatus
from .payment import PaymentCreate, PaymentGateway, PaymentResponse, PaymentStatus
from .products import (
    AlbumMini,
    ManagerProductFormPageRead,
    ManagerProductsPageRead,
    ProductBase,
    ProductCard,
    ProductCreate,
    ProductDetailRead,
    ProductRead,
    ProductSaleRead,
    ProductSalesPageRead,
    ProductUpdate,
    ProductWithDetailCreate,
    StorePageRead,
)
from .shipping import ShippingAddress, ShippingBase, ShippingStatus, ShippingStatusResponse

__all__ = [
    "AlbumDetailBase",
    "AlbumDetailCreate",
    "AlbumDetailUpdate",
    "AlbumDetailRead",
    "ArtistRef",
    "CartItem",
    "CartOut",
    "CartRead",
    "CategoryBase",
    "CategoryCreate",
    "CategoryUpdate",
    "CategoryRead",
    "GenreBase",
    "GenreCreate",
    "GenreRead",
    "AlbumGenreAssign",
    "AlbumGenreRead",
    "MerchDetailBase",
    "MerchDetailCreate",
    "MerchDetailUpdate",
    "MerchDetailRead",
    "OrderStatus",
    "OrderItem",
    "Order",
    "ManagerOrderItemRead",
    "ManagerOrderRead",
    "ManagerOrdersPageRead",
    "PaymentStatus",
    "PaymentGateway",
    "PaymentCreate",
    "PaymentResponse",
    "ProductBase",
    "ProductUpdate",
    "ProductCreate",
    "ProductRead",
    "ProductWithDetailCreate",
    "AlbumMini",
    "ProductCard",
    "StorePageRead",
    "ProductDetailRead",
    "ManagerProductsPageRead",
    "ManagerProductFormPageRead",
    "ProductSaleRead",
    "ProductSalesPageRead",
    "ShippingBase",
    "ShippingAddress",
    "ShippingStatus",
    "ShippingStatusResponse",
]
