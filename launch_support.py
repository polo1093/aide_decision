"""Shared helpers for the Tkinter launcher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from typing import Optional

from objet.services.controller import ControllerViewState
from objet.services.action_connector import enter_raise_amount_for_game as _enter_raise_amount_for_game
from objet.services.player_history import DEFAULT_PLAYER_HISTORY_DIR, player_history_path
from objet.utils.logging_config import get_logger


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_ROOT = PROJECT_ROOT / "config"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
INTERFACE_STATE_PATH = CONFIG_ROOT / "_interface_state.json"
DEFAULT_GAME_NAME = "PMU"
DEFAULT_WINDOW_GEOMETRY = "1080x760"
DEFAULT_SCAN_INTERVAL_MS = 1000
MIN_SCAN_INTERVAL_MS = 25
AUTO_IDENTIFY_COOLDOWN_SECONDS = 5.0
AUTO_CLICK_ARM_DELAY_SECONDS = 1.0
AUTO_CLICK_RETRY_SECONDS = 3.0
AUTO_CLICK_COMMAND_TTL_SECONDS = 1.5
VIDEO_FILETYPES = (
    ("Videos", "*.avi *.mp4 *.mkv *.mov"),
    ("Tous les fichiers", "*.*"),
)


@dataclass(frozen=True)
class TargetActionCommand:
    click_box: tuple[int, int, int, int]
    game_name: str
    decision_action: str
    raise_amount: Optional[float] = None
    runtime_offset: tuple[int, int] = (0, 0)
    hand_id: object = None
    street: str = ""
    target_button_label: str = ""
    target_button_state: str = ""
    target_button_value: Optional[float] = None
    queued_at: float = 0.0


class ProfileItem:
    def __init__(self, label: str, ok: bool, detail: str) -> None:
        self.label = label
        self.ok = ok
        self.detail = detail


def profile_status(
    game_name: str,
    config_root: Path | str = CONFIG_ROOT,
    history_root: Path | str = DEFAULT_PLAYER_HISTORY_DIR,
) -> list[ProfileItem]:
    game_dir = Path(config_root) / game_name
    action_files = ["check.png", "paie.png", "relance.png", "fold.png", "sit_out.png", "play.png"]
    cards_dir = game_dir / "Cards"
    cards_png = list(cards_dir.rglob("*.png")) if cards_dir.exists() else []
    history_item = _history_profile_item(game_name, history_root=history_root)
    return [
        _profile_item("Dossier", game_dir, "profil"),
        _profile_item("Coordinates", game_dir / "coordinates.json", "zones"),
        _profile_item("Anchor", game_dir / "anchor.png", "ancre"),
        ProfileItem("Cards", bool(cards_png), f"{len(cards_png)} templates" if cards_png else "templates manquants"),
        ProfileItem(
            "Actions",
            all((game_dir / name).exists() for name in action_files),
            f"{sum(1 for name in action_files if (game_dir / name).exists())}/{len(action_files)} fichiers",
        ),
        history_item,
    ]


def _profile_item(label: str, path: Path, detail: str) -> ProfileItem:
    return ProfileItem(label, path.exists(), detail if path.exists() else "manquant")


def _history_profile_item(game_name: str, *, history_root: Path | str) -> ProfileItem:
    path = player_history_path(game_name, root_dir=history_root)
    if not path.exists():
        return ProfileItem("Historique", True, "0 joueur")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        players = data.get("players", {}) if isinstance(data, dict) else {}
        count = len(players) if isinstance(players, dict) else 0
    except Exception:
        return ProfileItem("Historique", False, "illisible")
    return ProfileItem("Historique", True, f"{count} joueur(s)")


def available_game_names(config_root: Path | str = CONFIG_ROOT) -> list[str]:
    root = Path(config_root)
    if not root.exists():
        return [DEFAULT_GAME_NAME]
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "coordinates.json").exists()
    )
    return names or [DEFAULT_GAME_NAME]


def load_interface_state(path: Path | str = INTERFACE_STATE_PATH) -> dict[str, object]:
    state_path = Path(path)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("interface_state_lecture_impossible path=%s error=%s", state_path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def save_interface_state(state: dict[str, object], path: Path | str = INTERFACE_STATE_PATH) -> None:
    state_path = Path(path)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("interface_state_ecriture_impossible path=%s error=%s", state_path, exc)


def select_initial_game(cli_game: Optional[str], state: dict[str, object], profiles: list[str]) -> str:
    candidates: list[str] = []
    if cli_game:
        candidates.append(cli_game)
    saved_game = _state_text(state, "game_name")
    if saved_game:
        candidates.append(saved_game)
    candidates.append(DEFAULT_GAME_NAME)
    candidates.extend(profiles)

    for candidate in candidates:
        game = candidate.strip()
        if game and game in profiles:
            return game
    return DEFAULT_GAME_NAME


def needs_card_identification(state: ControllerViewState) -> bool:
    if not state.scan_ok:
        return False

    active_buttons = bool([button for button in state.buttons if button])
    street = str(state.street or "").upper()
    hero_cards = _pad_list(state.hero_state or state.hero_scan, 2)
    hero_known = _count_known_cards(hero_cards)
    if hero_known < 2 and active_buttons:
        return True
    if street != "IDLE" and hero_known < 2 and hero_known > 0:
        return True

    expected_board_count = {
        "FLOP": 3,
        "TURN": 4,
        "RIVER": 5,
    }.get(street, 0)
    if expected_board_count:
        board_cards = _pad_list(state.board_state or state.board_scan, 5)[:expected_board_count]
        board_known = _count_known_cards(board_cards)
        if board_known < expected_board_count and (board_known > 0 or active_buttons):
            return True

    return False


def _count_known_cards(values: list[object]) -> int:
    return sum(1 for value in values if value not in (None, "", "--"))


def _state_text(state: dict[str, object], key: str) -> Optional[str]:
    value = state.get(key)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def normalise_game_name(game_name: str) -> str:
    game = str(game_name).strip()
    if not game:
        raise ValueError("game_name is required")
    return game


def normalise_scan_interval_ms(value: object, *, fallback: int = DEFAULT_SCAN_INTERVAL_MS) -> int:
    try:
        interval = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return max(MIN_SCAN_INTERVAL_MS, interval)


def build_quick_setup_args(
    game_name: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
    video: Optional[str] = None,
    edit_zones: bool = True,
    extract_frames: bool = True,
    identify_cards: bool = True,
    validate_video: bool = True,
) -> list[str]:
    args = ["--game", normalise_game_name(game_name), "--config-root", str(Path(config_root))]
    if video:
        args += ["--video", str(video)]
    if not edit_zones:
        args.append("--skip-zone-editor")
    if not extract_frames:
        args.append("--skip-capture")
    if not identify_cards:
        args.append("--skip-identify")
    if not validate_video:
        args.append("--skip-capture-validation")
    return args


def build_zone_editor_args(game_name: str, *, config_root: Path | str = CONFIG_ROOT) -> list[str]:
    return build_quick_setup_args(
        game_name,
        config_root=config_root,
        extract_frames=False,
        identify_cards=False,
        validate_video=False,
    )


def build_capture_frames_args(
    game_name: str,
    video: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
) -> list[str]:
    game_dir = Path(config_root) / normalise_game_name(game_name)
    return ["--game-dir", str(game_dir), "--video", str(video)]


def build_identify_cards_args(game_name: str) -> list[str]:
    return ["--game", normalise_game_name(game_name)]


def build_validate_cards_args(
    game_name: str,
    video: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
) -> list[str]:
    game = normalise_game_name(game_name)
    game_dir = Path(config_root) / game
    return ["--game", game, "--game-dir", str(game_dir), "--video", str(video)]


def script_path_for(script_name: str) -> Path:
    path = SCRIPTS_ROOT / script_name
    if not path.is_file():
        raise FileNotFoundError(f"{path} n'existe pas.")
    return path


def _subprocess_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0


def build_interface_launch_command(
    command: list[str],
    *,
    cwd: Path | str = PROJECT_ROOT,
    launcher_dir: Path | str | None = None,
) -> list[str]:
    if not sys.platform.startswith("win"):
        return command
    launcher_root = Path(launcher_dir) if launcher_dir is not None else PROJECT_ROOT / "logs" / "tool_launchers"
    launcher_root.mkdir(parents=True, exist_ok=True)
    launcher_path = launcher_root / f"tool_{int(time.time() * 1000)}_{abs(hash(tuple(command))) & 0xffff:x}.cmd"
    command_line = subprocess.list2cmdline([str(part) for part in command])
    launcher_path.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'cd /d "{Path(cwd)}"',
                command_line,
                "set tool_exit=%ERRORLEVEL%",
                "echo.",
                "echo Termine avec code %tool_exit% . Appuie sur une touche pour fermer cette fenetre.",
                "pause >nul",
                "exit /b %tool_exit%",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ["cmd.exe", "/C", str(launcher_path)]


def format_command(command: list[str]) -> str:
    return " ".join(_quote_command_part(part) for part in command)


def _quote_command_part(part: str) -> str:
    text = str(part)
    if any(char.isspace() for char in text):
        return f'"{text}"'
    return text


def _fmt_optional_float(value: Optional[float]) -> str:
    if value is None:
        return "None"
    return f"{value:.1f}"


def _display_value(value: object) -> str:
    if value is None:
        return "---"
    return str(value)


def _display_percent(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return _display_value(value)


def _display_card(value: object) -> str:
    if value is None:
        return "--"
    return str(value)


def _target_button_bbox(target_button: Optional[dict[str, object]]) -> Optional[tuple[int, int, int, int]]:
    if not target_button:
        return None
    bbox = target_button.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    return tuple(int(value) for value in bbox)


def click_target_button_box(click_box: tuple[int, int, int, int]) -> object:
    """Click a target button bbox expressed as absolute screen x/y/width/height."""

    from personal_arc_click import click_xywh_box

    x, y, width, height = click_box
    target_point = (int(round(x + width / 2.0)), int(round(y + height / 2.0)))
    return click_xywh_box(
        click_box,
        button="left",
        target_point=target_point,
        inner_box_scale=0.92,
        click_box_scale=1.00,
        click_on_enter=False,
        delay_chance=0.0,
        pre_click_delay_min=0.025,
        pre_click_delay_max=0.08,
        min_duration=0.04,
        max_duration=0.10,
        spiral_radius=5.0,
        jitter=0.6,
    )


def enter_raise_amount_for_game(
    game_name: str,
    amount: object,
    *,
    runtime_offset: tuple[int, int] = (0, 0),
) -> Optional[str]:
    return _enter_raise_amount_for_game(
        game_name,
        amount,
        config_root=CONFIG_ROOT,
        runtime_offset=runtime_offset,
    )


def _decision_explanation(action: str, reason: str) -> str:
    explanations = {
        "new_party_pending_reset": "Nouvelle main detectee, attente du reset interne.",
        "hero_cards_not_detected_yet": "Cartes hero incompletes, pas de decision fiable.",
        "not_buttons": "Pas encore de bouton actif detecte.",
        "call_amount_not_detected": "Boutons actifs detectes, mais aucun check ni montant a payer fiable.",
        "equity_not_ready": "Equity pas encore calculee.",
        "equity_required_not_ready": "Equity minimale pas encore calculee.",
        "free_option_strong_equity": "Option gratuite et main forte: relance proposee.",
        "free_option_no_call_needed": "Aucun montant a payer: check propose.",
        "negative_call_ev": "Call non rentable: fold propose.",
        "small_bet_value_protection": "Petite mise adverse: relance de value/protection proposee.",
        "positive_edge_raise": "Relance proposee: equity nettement au-dessus de l'equity minimale.",
        "call_profitable_or_close": "Call rentable ou proche du seuil.",
    }
    detail = explanations.get(reason, reason)
    return f"{detail} ({reason})" if reason and detail != reason else detail


def _pad_list(values: list[object], size: int) -> list[object]:
    return list(values[:size]) + [None] * max(0, size - len(values))


def _style_card_label(label: tk.Label, value: object) -> None:
    text = _display_card(value)
    if text == "--":
        label.configure(bg="#f3f4f6", fg="#6b7280")
        return
    if "â™¥" in text or "â™¦" in text:
        label.configure(bg="#fff1f2", fg="#be123c")
        return
    if "â™£" in text:
        label.configure(bg="#ecfdf5", fg="#047857")
        return
    if "â™ " in text:
        label.configure(bg="#eff6ff", fg="#1d4ed8")
        return
    label.configure(bg="#ffffff", fg="#111827")


def _style_metric_label(label: Optional[tk.Label], value: object, *, positive_good: bool) -> None:
    if label is None:
        return
    number = _as_number(value)
    if number is None:
        label.configure(bg="#f3f4f6", fg="#374151")
        return
    good = number >= 0 if positive_good else number <= 0
    label.configure(
        bg="#dcfce7" if good else "#fee2e2",
        fg="#166534" if good else "#991b1b",
    )


def _style_equity_label(label: Optional[tk.Label], value: object) -> None:
    if label is None:
        return
    number = _as_number(value)
    if number is None:
        label.configure(bg="#f3f4f6", fg="#374151")
    elif number >= 0.55:
        label.configure(bg="#dcfce7", fg="#166534")
    elif number >= 0.35:
        label.configure(bg="#fef9c3", fg="#854d0e")
    else:
        label.configure(bg="#fee2e2", fg="#991b1b")


def _as_number(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _lighten_hex(color: str, amount: float) -> str:
    color = color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    red = min(255, int(red + (255 - red) * amount))
    green = min(255, int(green + (255 - green) * amount))
    blue = min(255, int(blue + (255 - blue) * amount))
    return f"#{red:02x}{green:02x}{blue:02x}"
