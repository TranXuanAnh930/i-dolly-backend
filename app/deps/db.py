from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import session


def get_db() -> Generator[Session, None, None]:
    db = session()
    try:
        yield db
    finally:
        db.close()