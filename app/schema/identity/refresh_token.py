import uuid
from datetime import datetime

from pydantic import BaseModel


class RefreshTokenCreate(BaseModel):

    id : uuid.UUID
    user_id : uuid.UUID
    token : str
    expires_at : datetime
    created_at : datetime

class RefreshTokenRead(RefreshTokenCreate):
    pass
