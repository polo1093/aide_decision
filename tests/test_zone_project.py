from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from zone_project import ZoneProject


def test_find_expected_image_prefers_training_screen_over_button_template(tmp_path: Path) -> None:
    game_dir = tmp_path / "PokerTH"
    screens_dir = game_dir / "entrainement" / "screens"
    screens_dir.mkdir(parents=True)
    (game_dir / "check.png").write_bytes(b"button")
    screen = screens_dir / "frame_000000.png"
    screen.write_bytes(b"screen")

    assert ZoneProject._find_expected_image(str(game_dir)) == str(screen)


def test_export_payload_preserves_region_metadata() -> None:
    project = ZoneProject()
    project.templates = {"player_card_symbol": {"size": [30, 34], "type": "carte_symbole"}}
    project.regions.clear()
    project.regions["player_card_1_symbol"] = {
        "group": "player_card_symbol",
        "top_left": [10, 20],
        "value": None,
        "label": "player_card_1_symbol",
        "template_set": "hand",
    }

    payload = project.export_payload()

    assert payload["regions"]["player_card_1_symbol"]["template_set"] == "hand"
