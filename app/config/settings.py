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

    # Celery uses the same Redis instance on a separate DB index from the cache/rate limiter.
    CELERY_BROKER_DB: int = 1
    DATABASE_NAME : str
    DATABASE_USER : str
    DATABASE_PWD : str
    FROM_EMAIL : str
    RESEND_API_KEY : str

    # When true, send_email() prints emails (including tokens) to the console instead of sending.
    # Dev only; never enable in production. Defaults to off so a missing env var fails safe.
    DEBUG: bool = False

    # Public URL of this API, used in links sent by email.
    BASE_URL: str = "http://localhost:8000"

    # Public URL of the frontend, used for PayPal return/cancel URLs.
    FRONTEND_BASE_URL: str = "http://localhost:8080"

    # Comma-separated origins allowed by CORS, e.g. "https://app.example.com,https://staging.example.com".
    CORS_ORIGINS: str = "http://localhost:8080"

    # --- image storage (app/utils/storage.py). "local" isn't durable on ephemeral hosts; use "s3".
    STORAGE_BACKEND: str = "local"  # "local" | "s3"
    LOCAL_UPLOAD_DIR: str = "uploads"
    LOCAL_UPLOAD_URL_PREFIX: str = "/uploads"

    # S3 or S3-compatible provider; required only when STORAGE_BACKEND=s3.
    S3_BUCKET_NAME: str | None = None
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None  # set for S3-compatible providers; unset for AWS
    S3_PUBLIC_URL_BASE: str | None = None  # CDN/custom domain; defaults to the bucket URL
    AWS_ACCESS_KEY_ID: str | None = None  # unset = boto3's default credential chain
    AWS_SECRET_ACCESS_KEY: str | None = None

    PAYPAL_CLIENT_ID: str | None = None
    PAYPAL_CLIENT_SECRET: str | None = None
    PAYPAL_MODE: str | None = None
    PAYPAL_WEBHOOK_ID: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
