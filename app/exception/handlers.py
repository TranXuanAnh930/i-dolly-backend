"""Error response shape: every error body is {"detail": ..., "code": ...}.

`detail` is unchanged from FastAPI's default (a string, or a list of field errors for a 422).
`code` is a stable snake_case identifier clients can branch on, taken from (in order):
1. the HTTPException itself (ApiHTTPException),
2. the service error it was raised from (`raise HTTPException(...) from e`, e a CodedError),
3. a default for the HTTP status.
"""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.exception.common import CodedError

logger = logging.getLogger(__name__)

STATUS_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class ApiHTTPException(HTTPException):
    """HTTPException with an explicit error code, for errors raised in a router."""

    def __init__(self, status_code: int, detail: str, code: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


def request_validation_error(exc: ValidationError) -> RequestValidationError:
    """Re-raise a model validated by hand (e.g. from Form fields) as FastAPI's own 422: a list of
    field errors located under the request body."""
    errors = exc.errors(include_url=False, include_context=False)
    return RequestValidationError([{**err, "loc": ("body", *err["loc"])} for err in errors])


def error_code(exc: StarletteHTTPException) -> str:
    if isinstance(exc, ApiHTTPException):
        return exc.code
    if isinstance(exc.__cause__, CodedError):
        return exc.__cause__.code
    return STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": error_code(exc)},
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "code": "validation_error"},
    )


class UnhandledErrorMiddleware:
    """Turns an unhandled exception into a JSON 500 ({"detail", "code": "internal_error"}).

    Must be added before CORSMiddleware so CORS wraps it: FastAPI's own 500 handler runs outside
    every middleware, so its response has no CORS headers and the browser reports a network error
    instead. The exception is logged with its traceback here, since it isn't re-raised."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if response_started:
                # Headers are already sent; nothing valid can be written now.
                raise
            response = JSONResponse(
                status_code=500, content={"detail": "Internal server error", "code": "internal_error"}
            )
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    # Starlette's HTTPException also covers unmatched routes (404) and wrong methods (405).
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
