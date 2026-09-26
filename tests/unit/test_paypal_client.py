import pytest

from app.utils.paypal_client import capture_id_from_response, order_id_from_webhook


@pytest.mark.parametrize("response, expected", [
    ({"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{"id": "CAPTURE-1", "status": "COMPLETED"}]}}]},
     "CAPTURE-1"),
    # first unit without a capture: take the next one that has it
    ({"purchase_units": [{"payments": {}}, {"payments": {"captures": [{"id": "CAPTURE-2"}]}}]}, "CAPTURE-2"),
    ({"status": "COMPLETED"}, None),
    ({"purchase_units": []}, None),
    ({"purchase_units": [{"payments": None}]}, None),
    ({"purchase_units": [{"payments": {"captures": [{}]}}]}, None),
])
def test_capture_id_from_response(response, expected):
    assert capture_id_from_response(response) == expected


@pytest.mark.parametrize("event, expected", [
    # CHECKOUT.ORDER.* carries the order itself
    ({"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "ORDER-1"}}, "ORDER-1"),
    # PAYMENT.CAPTURE.* carries the capture, with the order id alongside it
    ({"event_type": "PAYMENT.CAPTURE.COMPLETED",
      "resource": {"id": "CAPTURE-9", "supplementary_data": {"related_ids": {"order_id": "ORDER-2"}}}}, "ORDER-2"),
    # no event_type: treated like a capture event
    ({"resource": {"supplementary_data": {"related_ids": {"order_id": "ORDER-3"}}}}, "ORDER-3"),
    # events that don't refer to an order
    ({"event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "REFUND-1"}}, None),
    ({"event_type": "BILLING.PLAN.CREATED", "resource": {"id": "PLAN-1"}}, None),
    ({"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"supplementary_data": None}}, None),
    ({"event_type": "PAYMENT.CAPTURE.COMPLETED"}, None),
    ({"resource": "not-an-object"}, None),
    ([], None),
])
def test_order_id_from_webhook(event, expected):
    assert order_id_from_webhook(event) == expected
