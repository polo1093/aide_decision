from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from objet.utils.logging_config import (
    BACKUP_COUNT,
    DEFAULT_LOG_FILE,
    MAX_LOG_BYTES,
    configure_logging,
    get_logger,
    session_log,
)


def test_configure_logging_creates_rotating_debug_file_and_info_console(tmp_path, capsys) -> None:
    app_logger = configure_logging(log_dir=tmp_path, force=True)
    logger = get_logger("tests")

    logger.debug("debug fichier_only cle=1")
    logger.info("info console cle=2")
    _flush_handlers(app_logger)

    app_log = tmp_path / DEFAULT_LOG_FILE
    assert app_log.exists()

    content = app_log.read_text(encoding="utf-8")
    assert "DEBUG debug fichier_only cle=1" in content
    assert "INFO info console cle=2" in content

    captured = capsys.readouterr()
    assert "info console cle=2" in captured.err
    assert "debug fichier_only cle=1" not in captured.err

    file_handlers = [handler for handler in app_logger.handlers if isinstance(handler, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.DEBUG
    assert file_handlers[0].maxBytes == MAX_LOG_BYTES
    assert file_handlers[0].backupCount == BACKUP_COUNT

    console_handlers = [
        handler
        for handler in app_logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
    ]
    assert len(console_handlers) == 1
    assert console_handlers[0].level == logging.INFO


def test_session_log_contains_only_session_messages(tmp_path) -> None:
    app_logger = configure_logging(log_dir=tmp_path, force=True)
    logger = get_logger("tests.session")

    logger.info("hors_session avant=1")
    with session_log("operation", log_dir=tmp_path) as session_path:
        logger.debug("debug session step=1")
        logger.info("info session step=2")
    logger.info("hors_session apres=1")
    _flush_handlers(app_logger)

    content = session_path.read_text(encoding="utf-8")
    assert "DEBUG debug session step=1" in content
    assert "INFO info session step=2" in content
    assert "hors_session avant=1" not in content
    assert "hors_session apres=1" not in content


def _flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()
