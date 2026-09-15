from app.db.base_class import Base

from app.db.models.marketplace import Cart, Product, Category, Order, OrderItem, Payment, ShippingAddress, ShippingStatus
from app.db.models.identity import Users, RefreshToken
from app.db.models.talent import ManagementCompany, IdolColor, Position, IdolPosition, Group, Idol

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
from app.db.models.events import Venue, Concert, ConcertPerformer, TicketType, DirectSaleCampaign, LotteryPreference, LotteryCampaign, LotteryEntry, Ticket
from app.db.models.marketplace import AlbumDetail, Genre, AlbumGenre, MerchDetail
from app.db.models.shared import Notification
