"""Configuration de logging centralisee pour l'application."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator


APP_LOGGER_NAME = "aide_decision"
DEFAULT_LOG_DIR = Path("logs")
DEFAULT_LOG_FILE = "app.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

FILE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
CONSOLE_FORMAT = "%(message)s"
TIME_FORMAT = "%H:%M:%S"


def get_logger(name: str | None = None) -> logging.Logger:
    """Retourne un child logger de l'application."""

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    if not name:
        return app_logger
    clean_name = name.removeprefix(f"{APP_LOGGER_NAME}.")
    return app_logger.getChild(clean_name)


def configure_logging(
    *,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    force: bool = False,
) -> logging.Logger:
    """Configure la console INFO+ et le fichier rotatif DEBUG+."""

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False

    if app_logger.handlers and not force:
        return app_logger

    _clear_handlers(app_logger)

    file_handler = RotatingFileHandler(
        log_path / DEFAULT_LOG_FILE,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=TIME_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))

    app_logger.addHandler(file_handler)
    app_logger.addHandler(console_handler)
    return app_logger


@contextmanager
def session_log(
    operation: str,
    *,
    log_dir: Path | str = DEFAULT_LOG_DIR,
) -> Iterator[Path]:
    """Ajoute temporairement un fichier dedie aux logs d'une operation."""

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_path = log_path / f"{operation}_{timestamp}.log"

    handler = logging.FileHandler(session_path, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=TIME_FORMAT))

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False
    app_logger.addHandler(handler)
    try:
        yield session_path
    finally:
        app_logger.removeHandler(handler)
        handler.close()


def log_path_value(path: Path | str) -> str:
    """Formate un chemin de log stable pour les messages cle=valeur."""

    try:
        return str(Path(path).relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
