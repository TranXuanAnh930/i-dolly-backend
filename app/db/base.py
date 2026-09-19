from app.db.base_class import Base

from app.db.models.marketplace import Cart, Product, Category, Order, OrderItem, Payment, ShippingAddress, ShippingStatus
from app.db.models.identity import Users, RefreshToken
from app.db.models.talent import ManagementCompany, IdolColor, Position, IdolPosition, Group, Idol

# Every model must be imported here, in sync with app/db/models/. SQLAlchemy resolves
# string-based relationship targets (e.g. relationship("Cart", ...)) against whatever classes are
# already imported when mapper configuration runs — main.py's routers transitively import every
# model, so the live app never notices a gap, but a standalone script (scripts/seed.py) that
# imports models individually hits "failed to locate a name" if one is missing here.
from app.db.models.events import Venue, Concert, ConcertPerformer, TicketType, DirectSaleCampaign, LotteryPreference, LotteryCampaign, LotteryEntry, Ticket
from app.db.models.marketplace import AlbumDetail, Genre, AlbumGenre, MerchDetail
from app.db.models.shared import Notification
