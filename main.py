from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config.settings import settings
from app.db.session import session as SessionLocal
from app.router.events.concert import router as concert_router
from app.router.events.direct_sale_campaign import router as direct_sale_campaign_router
from app.router.events.lottery_campaign import router as lottery_campaign_router
from app.router.events.lottery_entry import router as lottery_entry_router
from app.router.events.lottery_preference import router as lottery_preference_router
from app.router.events.ticket import router as ticket_router
from app.router.events.ticket_type import router as ticket_type_router
from app.router.events.venue import router as venue_router
from app.router.identity.auth import router as auth_router
from app.router.identity.user import router as user_router
from app.router.marketplace.album_detail import router as album_detail_router
from app.router.marketplace.cart import router as cart_router
from app.router.marketplace.category import router as category_router
from app.router.marketplace.genre import router as genre_router
from app.router.marketplace.merch_detail import router as merch_detail_router
from app.router.marketplace.order import router as order_router
from app.router.marketplace.payment import router as payment_router
from app.router.marketplace.products import router as product_router
from app.router.marketplace.shipping import router as shipping_router
from app.router.shared.notification import router as notification_router
from app.router.talent.group import router as group_router
from app.router.talent.idol import router as idol_router
from app.router.talent.idol_color import router as idol_color_router
from app.router.talent.management_company import router as management_company_router
from app.router.talent.position import router as position_router
from app.services.identity.auth_service import AuthService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: delete expired and revoked refresh tokens.
    db = SessionLocal()
    try:
        AuthService.cleanup_expired_tokens(db)
    finally:
        db.close()
    yield

app = FastAPI(title="i-dolly-backend", lifespan=lifespan)

origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sets request.client.host from X-Forwarded-For so IP rate limits see the visitor, not Render's
# proxy. With trusted_hosts="*" uvicorn takes the leftmost hop, which a client can spoof
# (docs/bugs.md #7).
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Serves uploaded images when STORAGE_BACKEND=local; S3 URLs point at the bucket directly.
if settings.STORAGE_BACKEND == "local":
    Path(settings.LOCAL_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    app.mount(settings.LOCAL_UPLOAD_URL_PREFIX, StaticFiles(directory=settings.LOCAL_UPLOAD_DIR), name="uploads")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message" : "i-dolly-backend is live",
        "docs" : "/docs"
    }

app.include_router(product_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(category_router)
app.include_router(cart_router)
app.include_router(shipping_router)
app.include_router(order_router)
app.include_router(payment_router)
app.include_router(management_company_router)
app.include_router(idol_color_router)
app.include_router(position_router)
app.include_router(group_router)
app.include_router(idol_router)
app.include_router(venue_router)
app.include_router(concert_router)
app.include_router(ticket_type_router)
app.include_router(direct_sale_campaign_router)
app.include_router(lottery_preference_router)
app.include_router(lottery_campaign_router)
app.include_router(lottery_entry_router)
app.include_router(ticket_router)
app.include_router(album_detail_router)
app.include_router(genre_router)
app.include_router(merch_detail_router)
app.include_router(notification_router)
