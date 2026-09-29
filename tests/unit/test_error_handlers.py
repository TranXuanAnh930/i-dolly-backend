import inspect
import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from app.exception import checkout, common, db_triggers
from app.exception.common import BadRequestError, CodedError, NotFoundError
from app.exception.handlers import (
    ApiHTTPException,
    UnhandledErrorMiddleware,
    register_exception_handlers,
    request_validation_error,
)
from app.utils.storage import StorageError

# A throwaway app wired with the real handlers; each route raises one kind of error the way the
# real routers do.
app = FastAPI()
register_exception_handlers(app)


class _Body(BaseModel):
    quantity: int


@app.get("/service-error")
def _service_error() -> None:
    try:
        raise NotFoundError("Concert not found")
    except common.ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@app.get("/service-error-override")
def _service_error_override() -> None:
    try:
        raise BadRequestError("Entries for this lottery campaign have closed", code="entries_closed")
    except common.ServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@app.get("/checkout-error")
def _checkout_error() -> None:
    try:
        raise checkout.InsufficientTicketStockError("No tickets left for this tier")
    except checkout.CartItemError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/trigger-error")
def _trigger_error() -> None:
    try:
        raise db_triggers.DuplicateIdempotencyKeyError("uq_payment_idempotency_key")
    except db_triggers.TriggerViolationError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


@app.get("/plain")
def _plain() -> None:
    raise HTTPException(status_code=404, detail="Order not found")


@app.get("/unauthorized")
def _unauthorized() -> None:
    raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


@app.get("/api-exception")
def _api_exception() -> None:
    raise ApiHTTPException(status_code=401, detail="Invalid credentials", code="invalid_credentials")


@app.get("/unrelated-cause")
def _unrelated_cause() -> None:
    try:
        raise ValueError("bad")
    except ValueError as e:
        raise HTTPException(status_code=422, detail="bad input") from e


@app.post("/validate")
def _validate(body: _Body) -> None:
    return None


client = TestClient(app)


@pytest.mark.parametrize(
    ("path", "status", "detail", "code"),
    [
        ("/service-error", 404, "Concert not found", "not_found"),
        ("/service-error-override", 400, "Entries for this lottery campaign have closed", "entries_closed"),
        ("/checkout-error", 400, "No tickets left for this tier", "sold_out"),
        ("/trigger-error", 409, "uq_payment_idempotency_key", "duplicate_idempotency_key"),
        ("/plain", 404, "Order not found", "not_found"),
        ("/api-exception", 401, "Invalid credentials", "invalid_credentials"),
        ("/unrelated-cause", 422, "bad input", "validation_error"),
    ],
)
def test_error_body_has_detail_and_code(path, status, detail, code):
    response = client.get(path)
    assert response.status_code == status
    assert response.json() == {"detail": detail, "code": code}


def test_headers_are_kept():
    response = client.get("/unauthorized")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "not_authenticated"


def test_unknown_route_and_wrong_method():
    assert client.get("/no-such-route").json() == {"detail": "Not Found", "code": "not_found"}
    response = client.post("/plain")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


def test_request_validation_keeps_field_errors():
    response = client.post("/validate", json={"quantity": "many"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["loc"] == ["body", "quantity"]


def _coded_classes():
    for module in (common, checkout, db_triggers):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, CodedError) and cls is not CodedError:
                yield cls


@pytest.mark.parametrize("cls", sorted(set(_coded_classes()), key=lambda c: c.__name__), ids=lambda c: c.__name__)
def test_every_error_class_has_a_snake_case_code(cls):
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", cls.code)
    assert cls.code != CodedError.code


def test_code_override_is_per_instance():
    overridden = BadRequestError("x", code="entries_closed")
    assert overridden.code == "entries_closed"
    assert BadRequestError("y").code == "bad_request"
    assert str(overridden) == "x"


@app.get("/storage-error")
def _storage_error() -> None:
    try:
        raise StorageError("Unsupported image type")
    except StorageError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def test_upload_errors_have_their_own_code():
    assert client.get("/storage-error").json() == {"detail": "Unsupported image type", "code": "invalid_image"}


class _Form(BaseModel):
    track_count: int = Field(ge=1)


@app.post("/manual-validation")
def _manual_validation(track_count: int) -> None:
    try:
        _Form(track_count=track_count)
    except ValidationError as e:
        raise request_validation_error(e) from e


def test_hand_validated_model_gets_the_same_422_shape():
    response = client.post("/manual-validation", params={"track_count": 0})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["detail"][0]["loc"] == ["body", "track_count"]
    assert body["detail"][0]["type"] == "greater_than_equal"


# --- unexpected errors: same middleware order as main.py (CORS outside UnhandledErrorMiddleware)

ORIGIN = "http://localhost:8080"


def _app_with_cors(with_middleware: bool) -> FastAPI:
    crash_app = FastAPI()
    register_exception_handlers(crash_app)
    if with_middleware:
        crash_app.add_middleware(UnhandledErrorMiddleware)
    crash_app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_credentials=True)

    @crash_app.get("/crash")
    def _crash() -> None:
        raise RuntimeError("boom")

    return crash_app


def test_unexpected_error_is_json_500_with_cors_headers():
    crash_client = TestClient(_app_with_cors(with_middleware=True))
    response = crash_client.get("/crash", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error", "code": "internal_error"}
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_without_the_middleware_the_500_has_no_cors_headers():
    # Negative control: FastAPI's own 500 response is built outside CORSMiddleware.
    crash_client = TestClient(_app_with_cors(with_middleware=False), raise_server_exceptions=False)
    response = crash_client.get("/crash", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert "access-control-allow-origin" not in response.headers
