"""Generic service-layer failures a router turns into a clean HTTP response —
the replacement for this codebase's older sentinel-string convention
(`return "forbidden"` / `return "not_found"`) and its paired
`_raise_for(result)` / `_raise_for_link(result)` router helpers. Mirrors
app/exception/db_triggers.py's own shape (a base class carrying a
status_code, subclasses for the common cases) rather than introducing a
third pattern — see docs/architecture.md SS2.

Usage in a service function:

    from app.exception.common import ForbiddenError, NotFoundError

    if not company:
        raise NotFoundError("Management company not found")
    if _manager_scope_violation(current_user, company.id):
        raise ForbiddenError("Managers can only manage groups for their own company")

Usage in the router — one line, since the status code travels with the
exception class, same as TriggerViolationError:

    from app.exception.common import ServiceError

    try:
        return GroupService.add_group(db, group, current_user)
    except ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
"""


class ServiceError(Exception):
    """Base for every error in this module. Never raised directly — always
    one of the subclasses below, constructed with the specific message for
    that failure. Defaults to 400 so a new subclass that forgets to set
    status_code fails safe as a client error, not an unhandled 500."""
    status_code = 400


class NotFoundError(ServiceError):
    """A referenced row (company/group/idol/ticket type/...) doesn't exist.
    Raise this at the exact point a specific lookup fails, with a message
    naming that specific thing — not a blanket message covering every
    possible not-found reason in the function, the way the router-supplied
    not_found_detail this replaces had to."""
    status_code = 404


class ForbiddenError(ServiceError):
    """The caller is authenticated and the resource exists, but the action
    isn't allowed for this caller — wrong company, wrong role, a field
    that's locked once a resource reaches a certain state. An
    authorization failure, not a validation one, so 403 rather than 400."""
    status_code = 403


class BadRequestError(ServiceError):
    """A business-rule violation that isn't about existence or permission —
    a duplicate, a cross-field mismatch, a state that blocks the action
    (e.g. attaching a new release to a deactivated idol). Uses
    ServiceError's default 400."""
