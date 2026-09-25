from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Sized against Supabase's connection cap, shared with the Celery worker —
    # not against the ~40-thread FastAPI threadpool. Short transactions mean a
    # handful of connections serve many concurrent requests.
    pool_size=5,
    max_overflow=5,
    # Fail fast (503/500 in seconds) instead of 30s of queued threads.
    pool_timeout=10,
)

session = sessionmaker(autocommit = False, autoflush=False, bind=engine)
