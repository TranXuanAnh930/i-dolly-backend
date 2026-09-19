"""Generic response shapes shared across every router — not owned by any one
domain, same rationale as app/exception/common.py living outside every
domain subpackage. Replaces a router returning a bare `{"msg": "..."}` dict
literal (typed only as `dict[str, str]`, so OpenAPI sees an untyped object
with no documented field) with a named, documented Pydantic model. The JSON
body a client receives is unchanged — `MessageResponse(msg="...")`
serializes to exactly `{"msg": "..."}` — this is a schema/documentation
improvement, not an API contract change.
"""

from pydantic import BaseModel


class MessageResponse(BaseModel):
    msg: str
