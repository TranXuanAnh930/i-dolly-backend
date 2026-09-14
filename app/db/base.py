from app.db.base_class import Base

from app.db.models.marketplace.cart import Cart
from app.db.models.marketplace.products import Product
from app.db.models.marketplace.category import Category
from app.db.models.marketplace.order import Order, OrderItem
from app.db.models.marketplace.payment import Payment
from app.db.models.marketplace.shipping import ShippingAddress, ShippingStatus
from app.db.models.identity.user import Users
from app.db.models.identity.refresh_token import RefreshToken
from app.db.models.talent.management_company import ManagementCompany
from app.db.models.talent.idol_color import IdolColor
from app.db.models.talent.position import Position, IdolPosition
from app.db.models.talent.group import Group
from app.db.models.talent.idol import Idol

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
from app.db.models.events.venue import Venue
from app.db.models.events.concert import Concert, ConcertPerformer
from app.db.models.events.ticket_type import TicketType
from app.db.models.events.direct_sale_campaign import DirectSaleCampaign
from app.db.models.events.lottery_preference import LotteryPreference
from app.db.models.events.lottery_campaign import LotteryCampaign
from app.db.models.events.lottery_entry import LotteryEntry
from app.db.models.events.ticket import Ticket
from app.db.models.marketplace.album_detail import AlbumDetail
from app.db.models.marketplace.genre import Genre, AlbumGenre
from app.db.models.marketplace.merch_detail import MerchDetail
from app.db.models.shared.notification import Notification
