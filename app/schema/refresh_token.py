import uuid
from pydantic import BaseModel
from datetime import datetime

class RefreshTokenCreate(BaseModel):

    id : uuid.UUID
    user_id : uuid.UUID
    token : str
    expires_at : datetime
    created_at : datetime

class RefreshTokenRead(RefreshTokenCreate):
    pass
