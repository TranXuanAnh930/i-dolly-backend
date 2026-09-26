"""Service-layer errors that carry their own HTTP status code.

Raise from a service; catch ServiceError once in the router:

    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
"""


class ServiceError(Exception):
    """Base class; only subclasses are raised. Defaults to 400."""
    status_code = 400


class NotFoundError(ServiceError):
    """A referenced row doesn't exist (404)."""
    status_code = 404


class ForbiddenError(ServiceError):
    """The caller isn't allowed to do this, e.g. wrong company or role (403)."""
    status_code = 403


class BadRequestError(ServiceError):
    """A business-rule violation such as a duplicate or a blocking state (400)."""
