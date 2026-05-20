"""Tests for launcher tool command helpers."""
from __future__ import annotations

import queue
from pathlib import Path
from types import SimpleNamespace

import pytest

from launch import (
    App,
    available_game_names,
    build_interface_launch_command,
    build_capture_frames_args,
    build_identify_cards_args,
    build_quick_setup_args,
    build_validate_cards_args,
    build_zone_editor_args,
    click_target_button_box,
    format_command,
    load_interface_state,
    needs_card_identification,
    normalise_game_name,
    normalise_scan_interval_ms,
    profile_status,
    save_interface_state,
    select_initial_game,
    script_path_for,
)
from objet.services.controller import ControllerViewState


def test_available_game_names_lists_profiles_with_coordinates(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    (config_root / "PMU").mkdir(parents=True)
    (config_root / "PMU" / "coordinates.json").write_text("{}", encoding="utf-8")
    (config_root / "NoCoords").mkdir()

    assert available_game_names(config_root) == ["PMU"]


def test_available_game_names_falls_back_to_pmu_for_missing_root(tmp_path: Path) -> None:
    assert available_game_names(tmp_path / "missing") == ["PMU"]


def test_interface_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_interface_state(
        {
            "game_name": "PokerTH",
            "window_geometry": "1200x800+10+20",
            "window_state": "zoomed",
        },
        path,
    )

    assert load_interface_state(path) == {
        "game_name": "PokerTH",
        "window_geometry": "1200x800+10+20",
        "window_state": "zoomed",
    }


def test_select_initial_game_uses_cli_then_saved_then_default() -> None:
    profiles = ["PMU", "PokerTH"]

    assert select_initial_game("PMU", {"game_name": "PokerTH"}, profiles) == "PMU"
    assert select_initial_game(None, {"game_name": "PokerTH"}, profiles) == "PokerTH"
    assert select_initial_game(None, {"game_name": "Missing"}, profiles) == "PMU"


def test_script_path_for_resolves_existing_script() -> None:
    assert script_path_for("quick_setup.py").name == "quick_setup.py"


def test_normalise_game_name_rejects_blank_values() -> None:
    with pytest.raises(ValueError):
        normalise_game_name("   ")


def test_normalise_scan_interval_accepts_large_values() -> None:
    assert normalise_scan_interval_ms("200000") == 200000


def test_normalise_scan_interval_keeps_minimum_and_fallback() -> None:
    assert normalise_scan_interval_ms("1") == 25
    assert normalise_scan_interval_ms("pas un nombre", fallback=750) == 750


def test_build_quick_setup_args_includes_video_and_selected_skip_flags(tmp_path: Path) -> None:
    args = build_quick_setup_args(
        " PMU ",
        config_root=tmp_path / "config",
        video=r"C:\captures\cards video.mp4",
        edit_zones=False,
        extract_frames=True,
        identify_cards=False,
        validate_video=False,
    )

    assert args == [
        "--game",
        "PMU",
        "--config-root",
        str(tmp_path / "config"),
        "--video",
        r"C:\captures\cards video.mp4",
        "--skip-zone-editor",
        "--skip-identify",
        "--skip-capture-validation",
    ]


def test_build_zone_editor_args_runs_only_zone_step(tmp_path: Path) -> None:
    args = build_zone_editor_args("PMU", config_root=tmp_path / "config")

    assert args == [
        "--game",
        "PMU",
        "--config-root",
        str(tmp_path / "config"),
        "--skip-capture",
        "--skip-identify",
        "--skip-capture-validation",
    ]


def test_individual_script_args_use_selected_profile(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    video = r"C:\captures\cards_video.avi"

    assert build_capture_frames_args("PMU", video, config_root=config_root) == [
        "--game-dir",
        str(config_root / "PMU"),
        "--video",
        video,
    ]
    assert build_identify_cards_args("PMU") == ["--game", "PMU"]
    assert build_validate_cards_args("PMU", video, config_root=config_root) == [
        "--game",
        "PMU",
        "--game-dir",
        str(config_root / "PMU"),
        "--video",
        video,
    ]


def test_format_command_quotes_parts_with_spaces() -> None:
    assert format_command(["python", r"C:\with space\tool.py", "--game", "PMU"]) == (
        'python "C:\\with space\\tool.py" --game PMU'
    )


def test_profile_status_reports_player_history_count(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    history_root = tmp_path / "history"
    game_dir = config_root / "PMU"
    game_dir.mkdir(parents=True)
    (game_dir / "coordinates.json").write_text("{}", encoding="utf-8")
    history_root.mkdir()
    (history_root / "PMU.json").write_text('{"players": {"Alice": {}, "Bob": {}}}', encoding="utf-8")

    items = profile_status("PMU", config_root=config_root, history_root=history_root)

    assert items[-1].label == "Historique"
    assert items[-1].ok is True
    assert items[-1].detail == "2 joueur(s)"


def test_interface_launch_command_pauses_on_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("launch.sys.platform", "win32")

    command = build_interface_launch_command(
        ["python", r"C:\with space\tool.py", "--game", "PokerTH"],
        cwd=tmp_path,
        launcher_dir=tmp_path,
    )

    assert command[:2] == ["cmd.exe", "/C"]
    launcher = Path(command[2])
    content = launcher.read_text(encoding="utf-8")
    assert "pause >nul" in content
    assert '"C:\\with space\\tool.py"' in content
    assert "PokerTH" in content


def test_interface_launch_command_is_raw_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("launch.sys.platform", "linux")
    command = ["python", "tool.py"]

    assert build_interface_launch_command(command) is command


def test_needs_card_identification_for_partial_hero_preflop() -> None:
    state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        street="PREFLOP",
        hero_scan=["Q♥", None],
        board_scan=[None, None, None, None, None],
        buttons=["B0 relance :20.0", "B1 check"],
    )

    assert needs_card_identification(state) is True


def test_needs_card_identification_for_partial_hero_idle_with_buttons() -> None:
    state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        street="IDLE",
        hero_scan=["Q♥", None],
        board_scan=[None, None, None, None, None],
        buttons=["B0 relance :820.0", "B1 check", "B2 fold"],
    )

    assert needs_card_identification(state) is True


def test_needs_card_identification_ignores_empty_idle_table() -> None:
    state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        street="IDLE",
        hero_scan=[None, None],
        board_scan=[None, None, None, None, None],
        buttons=[],
    )

    assert needs_card_identification(state) is False


def test_needs_card_identification_for_partial_flop_board() -> None:
    state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        street="FLOP",
        hero_scan=["A♠", "K♥"],
        board_scan=["2♣", None, "9♦", None, None],
        buttons=[],
    )

    assert needs_card_identification(state) is True


def test_live_unread_card_selects_visible_missing_hero_card() -> None:
    app = App.__new__(App)

    known_card = SimpleNamespace(
        formatted="Q♥",
        card_coordinates_value=(1, 2, 3, 4),
        card_coordinates_suit=(5, 6, 7, 8),
        template_set="hand",
    )
    missing_card = SimpleNamespace(
        formatted=None,
        card_coordinates_value=(10, 20, 30, 40),
        card_coordinates_suit=(50, 60, 70, 80),
        template_set="hand",
    )
    cards = SimpleNamespace(
        me_cards=lambda: [known_card, missing_card],
        board_cards=lambda: [],
    )
    scan = SimpleNamespace(
        screen_array=object(),
        _extract_patch=lambda box, pad=3: ("patch", box, pad),
    )
    app.controller = SimpleNamespace(game=SimpleNamespace(table=SimpleNamespace(cards=cards, scan=scan)))
    app._live_card_patch_is_hand_overlay = lambda _scan, _card, _patch: False
    app._live_card_patch_present = lambda _patch: True
    app._bgr_patch_to_pil = lambda patch: patch

    state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        street="PREFLOP",
        hero_scan=["Q♥", None],
        board_scan=[None, None, None, None, None],
        buttons=["B0 call"],
    )

    result = App._find_live_unread_card(app, state)

    assert result is not None
    base_key, card, number_patch, suit_patch = result
    assert base_key == "player_card_2"
    assert card is missing_card
    assert number_patch == ("patch", (10, 20, 30, 40), 3)
    assert suit_patch == ("patch", (50, 60, 70, 80), 3)


def test_target_button_screen_bbox_applies_runtime_region_offset() -> None:
    app = App.__new__(App)
    app.controller = SimpleNamespace(
        game=SimpleNamespace(
            table=SimpleNamespace(
                scan=SimpleNamespace(runtime_region_offset=(15, -7)),
            ),
        ),
    )

    bbox = App._target_button_screen_bbox(
        app,
        {"bbox": [100, 200, 30, 40]},
    )

    assert bbox == (115, 193, 30, 40)


def test_auto_click_queues_absolute_target_box_once() -> None:
    app = App.__new__(App)
    app.controller = SimpleNamespace(
        game=SimpleNamespace(
            table=SimpleNamespace(
                scan=SimpleNamespace(runtime_region_offset=(5, 10)),
            ),
        ),
    )
    app.var_auto_click_target = _Var(True)
    app.var_click_status = _Var("")
    app._click_queue = queue.Queue()
    app._last_click_signature = None
    app._last_click_queued_at = 0.0

    state = ControllerViewState(
        game_name="PMU",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=42,
        decision_action="CALL",
        target_button={
            "label": "B1",
            "state": "paie",
            "bbox": [100, 200, 30, 40],
        },
    )

    App._maybe_queue_target_click(app, state)
    App._maybe_queue_target_click(app, state)

    assert app._click_queue.get_nowait() == (105, 210, 30, 40)
    assert app._click_queue.empty()


def test_auto_click_requeues_same_target_after_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
    app.controller = SimpleNamespace(
        game=SimpleNamespace(
            table=SimpleNamespace(
                scan=SimpleNamespace(runtime_region_offset=(5, 10)),
            ),
        ),
    )
    app.var_auto_click_target = _Var(True)
    app.var_click_status = _Var("")
    app._click_queue = queue.Queue()
    app._last_click_signature = None
    app._last_click_queued_at = 0.0
    times = iter([100.0, 101.0, 103.1])
    monkeypatch.setattr("launch.time.monotonic", lambda: next(times))

    state = ControllerViewState(
        game_name="PMU",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=42,
        decision_action="CHECK",
        target_button={
            "label": "B1",
            "state": "check",
            "bbox": [100, 200, 30, 40],
        },
    )

    App._maybe_queue_target_click(app, state)
    App._maybe_queue_target_click(app, state)
    App._maybe_queue_target_click(app, state)

    assert app._click_queue.get_nowait() == (105, 210, 30, 40)
    assert app._click_queue.get_nowait() == (105, 210, 30, 40)
    assert app._click_queue.empty()


def test_left_click_box_uses_human_clicker_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
    calls = []

    monkeypatch.setattr("launch.click_target_button_box", lambda box: calls.append(box))

    App._left_click_box_center(app, (10, 20, 30, 40))

    assert calls == [(10, 20, 30, 40)]


def test_click_target_button_box_passes_clicker_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_click_xywh_box(box, **kwargs):
        calls.append((box, kwargs))
        return "clicked"

    monkeypatch.setattr("objet.utils.human_clicker.click_xywh_box", fake_click_xywh_box)

    assert click_target_button_box((10, 20, 30, 40)) == "clicked"
    assert calls == [
        (
            (10, 20, 30, 40),
            {
                "button": "left",
                "inner_box_scale": 0.92,
                "click_box_scale": 0.50,
                "delay_chance": 0.0,
                "pre_click_delay_min": 0.025,
                "pre_click_delay_max": 0.08,
                "min_duration": 0.04,
                "max_duration": 0.10,
                "spiral_radius": 8.0,
                "jitter": 1.5,
            },
        )
    ]


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value
