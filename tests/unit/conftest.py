from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_celery_dispatch():
    """Every unit test in this tree calls service functions directly with a MagicMock db — none of
    them should ever reach a real Celery worker, and through it a real Resend send or a real
    lottery draw. Autouse so a test doesn't have to remember to mock celery_app.send_task itself —
    test_lottery_draw_service.py's win/loss tests didn't, and were quietly enqueuing real
    LOTTERY_WON/LOTTERY_LOST email tasks on every run (see docs/project_status.md). Patches the
    shared celery_app instance's own method, so it takes effect regardless of which module did
    `from app.celery_app import celery_app`. A test that wants to assert on the call can still
    request this fixture by name to get the mock.
    """
    with patch("app.celery_app.celery_app.send_task") as mock_send_task:
        yield mock_send_task
