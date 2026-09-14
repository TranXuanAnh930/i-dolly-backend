from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL : str
    JWT_SECRET_KEY : str
    JWT_REFRESH_SECRET_KEY : str
    JWT_EMAIL_SECRET_KEY : str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES : int
    REFRESH_TOKEN_EXPIRE_DAYS : int
    EMAIL_TOKEN_EXPIRE_MINUTES : int
    REDIS_HOST : str
    REDIS_PORT : int
    REDIS_DB : int

    # Celery broker/result backend — same Redis instance as REDIS_HOST/PORT
    # above, but a different DB index so task/result keys never collide with
    # the product-list cache or rate-limiter counters living in REDIS_DB.
    CELERY_BROKER_DB: int = 1
    DATABASE_NAME : str
    DATABASE_USER : str
    DATABASE_PWD : str
    SENDGRID_API_KEY : str
    FROM_EMAIL : str

    # Dev convenience only, defaults off. `.env.example`'s SENDGRID_API_KEY
    # is a placeholder, so a real send always fails locally — when true,
    # send_email() prints the full email body (including whatever
    # verification/reset token it carries) to the console before attempting
    # to send, and swallows the resulting SendGrid failure instead of
    # letting it raise inside a BackgroundTask. Never set true in production:
    # these bodies carry live auth tokens, which have no business sitting in
    # a shared server log.
    DEBUG: bool = True

    # Public base URL of this API — used to build links (e.g. the email
    # verification link) that must resolve from outside the container.
    # Defaults to local dev; override per-environment via .env.
    BASE_URL: str = "http://localhost:8000"

    # Public base URL of the frontend — used to build PayPal's return_url/
    # cancel_url (app/utils/paypal_client.py's create_order) so the buyer
    # lands back on the SPA, not this API. Defaults to the local Vite dev
    # port; override per-environment via .env.
    FRONTEND_BASE_URL: str = "http://localhost:8080"

    # Comma-separated list of frontend origins allowed to call this API
    # cross-origin (see main.py's CORSMiddleware). Defaults to the local Vue
    # dev port; set to the deployed frontend's real origin(s) in production —
    # e.g. "https://my-frontend.vercel.app,https://staging.my-frontend.app".
    CORS_ORIGINS: str = "http://localhost:8080"

    # --- image storage (see app/utils/storage.py) ------------------------
    # "local" saves to LOCAL_UPLOAD_DIR on disk, served back out under
    # LOCAL_UPLOAD_URL_PREFIX (main.py mounts it via StaticFiles) — fine for
    # local dev, and it happens to persist across container restarts here
    # too since docker-compose.yaml already bind-mounts the whole app dir.
    # Not durable for a real multi-instance/ephemeral-filesystem deploy
    # though — flip STORAGE_BACKEND to "s3" for that, no code changes
    # needed at any call site.
    STORAGE_BACKEND: str = "local"  # "local" | "s3"
    LOCAL_UPLOAD_DIR: str = "uploads"
    LOCAL_UPLOAD_URL_PREFIX: str = "/uploads"

    # S3 (or any S3-compatible provider: DigitalOcean Spaces, Cloudflare R2,
    # MinIO, ...). All optional so a local-only .env keeps working — only
    # required once STORAGE_BACKEND=s3.
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None  # set for an S3-compatible provider; leave unset for real AWS S3
    S3_PUBLIC_URL_BASE: str | None = None  # CDN/custom domain fronting the bucket; falls back to a computed bucket URL when unset
    AWS_ACCESS_KEY_ID: str | None = None  # falls back to boto3's normal credential chain (env, shared config, IAM role) if unset
    AWS_SECRET_ACCESS_KEY: str | None = None

    PAYPAL_CLIENT_ID: str | None = None
    PAYPAL_CLIENT_SECRET: str | None = None
    PAYPAL_MODE: str | None = None
    PAYPAL_WEBHOOK_ID: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
