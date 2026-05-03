"""Debug capture helpers for blocking runtime errors."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Optional

from PIL import ImageGrab

from objet.utils.logging_config import DEFAULT_LOG_DIR, get_logger, log_path_value


LOGGER = get_logger(__name__)


def capture_blocking_error_screen(
    *,
    context: str,
    log_dir: Path | str = DEFAULT_LOG_DIR,
) -> Optional[Path]:
    """Save a full-screen PNG when a blocking runtime error occurs."""

    output_dir = Path(log_dir) / "errors"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    context_slug = _slugify(context)
    output_path = output_dir / f"blocking_{timestamp}_{context_slug}.png"

    try:
        ImageGrab.grab().save(output_path)
    except Exception as exc:  # pragma: no cover - depends on local display state.
        LOGGER.warning("SKIP capture_erreur_blocante raison=%s", exc)
        return None

    LOGGER.info("CAPTURE erreur_blocante path=%s", log_path_value(output_path))
    return output_path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return slug or "unknown"


__all__ = ["capture_blocking_error_screen"]
