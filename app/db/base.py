from app.db.base_class import Base

from app.db.models.cart import Cart
from app.db.models.products import Product
from app.db.models.category import Category
from app.db.models.order import Order, OrderItem
from app.db.models.payment import Payment
from app.db.models.shipping import ShippingAddress, ShippingStatus
from app.db.models.user import Users
from app.db.models.refresh_token import RefreshToken
from app.db.models.management_company import ManagementCompany
from app.db.models.idol_color import IdolColor
from app.db.models.position import Position, IdolPosition
from app.db.models.group import Group
from app.db.models.idol import Idol

# CORRECTION: everything below was added by later migration rounds
# (database-design.md §7.5/§8) but never registered here, so this file
# silently drifted out of sync with app/db/models/. That's more than
# cosmetic: SQLAlchemy resolves string-based relationship targets (e.g.
# `relationship("Cart", ...)`) against whatever classes happen to be
# imported by the time mapper configuration is triggered — the live app
# never noticed because main.py imports every router, which transitively
# imports every model anyway, but any standalone script that imports models
# individually (like scripts/seed.py) hits "failed to locate a name" the moment it
# touches a class whose relationships point at something never imported.
# This file is the one place that's supposed to guarantee every model is
# registered regardless of what else got imported — keep it in sync with
# app/db/models/ going forward.
from app.db.models.venue import Venue
from app.db.models.concert import Concert, ConcertPerformer
from app.db.models.ticket_type import TicketType
from app.db.models.lottery_preference import LotteryPreference
from app.db.models.lottery_campaign import LotteryCampaign
from app.db.models.lottery_entry import LotteryEntry
from app.db.models.ticket import Ticket
from app.db.models.album_detail import AlbumDetail
from app.db.models.genre import Genre, AlbumGenre
from app.db.models.merch_detail import MerchDetail
from app.db.models.notification import Notification
