"""Tests for the `objet.scanner.cards_recognition` module."""

from pathlib import Path
import sys
import types

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

pyautogui_stub = types.ModuleType("pyautogui")
pyautogui_stub.locate = lambda *_, **__: None
sys.modules.setdefault("pyautogui", pyautogui_stub)

from objet.scanner.cards_recognition import is_cover_me_cards


def test_cover_overlay_is_detected() -> None:
    """The training cover image should be recognised as the overlay."""

    cover_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "PMU"
        / "entrainement"
        / "cover.PNG"
    )

    with Image.open(cover_path) as cover_image:
        assert is_cover_me_cards(cover_image, threshold=0.55) is True







if __name__ == "__main__":
    test_cover_overlay_is_detected()
