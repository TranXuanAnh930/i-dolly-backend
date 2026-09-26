"""Response models shared across routers."""

from pydantic import BaseModel


class MessageResponse(BaseModel):
    msg: str
