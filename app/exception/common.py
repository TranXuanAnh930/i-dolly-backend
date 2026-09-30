"""Service-layer errors that carry their own HTTP status code and error code.

Raise from a service; catch ServiceError once in the router:

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

The `from e` matters: app/exception/handlers.py reads `code` off the cause and adds it to the
response body as {"detail": ..., "code": ...}.
"""


class CodedError(Exception):
    """An error with a stable, machine-readable `code` (snake_case) for API clients.

    `code` is set per class; pass `code=` to override it for one raise site."""
    code = "error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ServiceError(CodedError):
    """Base class; only subclasses are raised. Defaults to 400."""
    status_code = 400
    code = "bad_request"


class NotFoundError(ServiceError):
    """A referenced row doesn't exist (404)."""
    status_code = 404
    code = "not_found"


class ForbiddenError(ServiceError):
    """The caller isn't allowed to do this, e.g. wrong company or role (403)."""
    status_code = 403
    code = "forbidden"


class BadRequestError(ServiceError):
    """A business-rule violation such as a duplicate or a blocking state (400)."""
    code = "bad_request"


class ConflictError(ServiceError):
    """The request conflicts with the resource's current state, e.g. already done (409)."""
    status_code = 409
    code = "conflict"
