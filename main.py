from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.router.products import router as product_router
from app.router.auth import router as auth_router
from app.router.user import router as user_router
from app.router.category import router as category_router
from app.router.cart import router as cart_router
from app.router.shipping import router as shipping_router
from app.router.order import router as order_router
from app.router.payment import router as payment_router
from app.router.management_company import router as management_company_router
from app.router.idol_color import router as idol_color_router
from app.router.position import router as position_router
from app.router.group import router as group_router
from app.router.idol import router as idol_router
from app.router.venue import router as venue_router
from app.router.concert import router as concert_router
from app.router.ticket_type import router as ticket_type_router
from app.router.lottery_preference import router as lottery_preference_router
from app.router.lottery_campaign import router as lottery_campaign_router
from app.router.lottery_entry import router as lottery_entry_router
from app.router.ticket import router as ticket_router
from app.router.album_detail import router as album_detail_router
from app.router.genre import router as genre_router
from app.router.lightstick_detail import router as lightstick_detail_router
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from app.db.session import session as SessionLocal
from app.services.auth_service import cleanup_expired_tokens
from app.config.settings import settings
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: clean up expired refresh tokens
    db = SessionLocal()
    try:
        cleanup_expired_tokens(db)
    finally:
        db.close()
    yield

app = FastAPI(title="i-dolly-backend", lifespan=lifespan)

origins = [
    "http://localhost:8080",      # Vue port
]

# 2. Add CORSMiddleware to your FastAPI application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,           # Allows specific origins
    allow_credentials=True,          # Allows cookies/authorization headers
    allow_methods=["*"],             # Allows all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],             # Allows all request headers
)

# Serves uploaded idol/product images back out when STORAGE_BACKEND=local
# (app/utils/storage.py). Nothing to mount for STORAGE_BACKEND=s3 — those
# URLs point straight at the bucket/CDN instead.
if settings.STORAGE_BACKEND == "local":
    Path(settings.LOCAL_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    app.mount(settings.LOCAL_UPLOAD_URL_PREFIX, StaticFiles(directory=settings.LOCAL_UPLOAD_DIR), name="uploads")


@app.get("/")
def root():
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
app.include_router(lottery_preference_router)
app.include_router(lottery_campaign_router)
app.include_router(lottery_entry_router)
app.include_router(ticket_router)
app.include_router(album_detail_router)
app.include_router(genre_router)
app.include_router(lightstick_detail_router)
