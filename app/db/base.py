from app.db.base_class import Base

from app.db.models.marketplace import Cart, Product, Category, Order, OrderItem, Payment, ShippingAddress, ShippingStatus
from app.db.models.identity import Users, RefreshToken
from app.db.models.talent import ManagementCompany, IdolColor, Position, IdolPosition, Group, Idol

# Import every model so SQLAlchemy can resolve string relationship targets in standalone scripts
# (e.g. scripts/seed.py, Celery tasks). Keep in sync with app/db/models/.
from app.db.models.events import Venue, Concert, ConcertPerformer, TicketType, DirectSaleCampaign, LotteryPreference, LotteryCampaign, LotteryEntry, Ticket
from app.db.models.marketplace import AlbumDetail, Genre, AlbumGenre, MerchDetail
from app.db.models.shared import Notification
