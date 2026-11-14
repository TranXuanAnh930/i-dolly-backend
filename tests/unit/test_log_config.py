import logging
import sys
from unittest.mock import patch

import pytest

from app.config.log_config import APP_LOGGER, configure_logging


@pytest.fixture
def bare_root():
    """The root logger with no handlers, as under uvicorn, restored afterwards. pytest attaches
    its own capture handlers when the test body starts, so tests call strip() first."""
    root = logging.getLogger()
    app_logger = logging.getLogger(APP_LOGGER)
    saved = (root.handlers[:], root.level, app_logger.level)

    def strip():
        root.handlers = []
        return root

    yield strip
    root.handlers, root.level = saved[0], saved[1]
    app_logger.setLevel(saved[2])


def test_sets_the_app_level_from_settings(bare_root):
    bare_root()
    with patch("app.config.log_config.settings.LOG_LEVEL", "debug"):
        configure_logging()
    assert logging.getLogger(APP_LOGGER).level == logging.DEBUG
    assert logging.getLogger("app.services.anything").getEffectiveLevel() == logging.DEBUG


def test_adds_one_stdout_handler_and_is_idempotent(bare_root):
    root = bare_root()
    configure_logging()
    configure_logging()
    assert len(root.handlers) == 1
    assert root.handlers[0].stream is sys.stdout


def test_keeps_an_existing_root_handler(bare_root):
    # Celery's worker installs its own root handler; ours mustn't add a second one.
    root = bare_root()
    existing = logging.StreamHandler()
    root.addHandler(existing)
    configure_logging()
    assert root.handlers == [existing]


def test_library_loggers_stay_at_warning(bare_root):
    bare_root()
    configure_logging()
    assert logging.getLogger("sqlalchemy.engine").getEffectiveLevel() == logging.WARNING
