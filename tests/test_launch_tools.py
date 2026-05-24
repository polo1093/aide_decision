"""Tests for launcher tool command helpers."""
from __future__ import annotations

import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from launch import (
    App,
    CONFIG_ROOT,
    available_game_names,
    build_interface_launch_command,
    build_capture_frames_args,
    build_identify_cards_args,
    build_quick_setup_args,
    build_validate_cards_args,
    build_zone_editor_args,
    click_target_button_box,
    configure_console_output,
    enter_raise_amount_for_game,
    format_command,
    load_interface_state,
    needs_card_identification,
    normalise_game_name,
    normalise_scan_interval_ms,
    profile_status,
    parse_args,
    save_interface_state,
    select_initial_decision_mode,
    select_initial_game,
    select_initial_hero_position,
    script_path_for,
)
from objet.services.controller import ControllerViewState


class _ReconfigurableStream:
    def __init__(self) -> None:
        self.kwargs = None

    def reconfigure(self, **kwargs) -> None:
        self.kwargs = kwargs


def test_configure_console_output_sets_utf8_with_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = _ReconfigurableStream()
    stderr = _ReconfigurableStream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    configure_console_output()

    assert stdout.kwargs == {"encoding": "utf-8", "errors": "replace"}
    assert stderr.kwargs == {"encoding": "utf-8", "errors": "replace"}


def test_available_game_names_lists_profiles_with_coordinates(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    (config_root / "PMU").mkdir(parents=True)
    (config_root / "PMU" / "coordinates.json").write_text("{}", encoding="utf-8")
    (config_root / "NoCoords").mkdir()

    assert available_game_names(config_root) == ["PMU"]


def test_launch_exports_config_root_used_by_main_and_app_helpers() -> None:
    assert CONFIG_ROOT.name == "config"


def test_available_game_names_falls_back_to_pmu_for_missing_root(tmp_path: Path) -> None:
    assert available_game_names(tmp_path / "missing") == ["PMU"]


def test_interface_state_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_interface_state(
        {
            "game_name": "PokerTH",
            "decision_mode": "pokercharts",
            "hero_position": "CO",
            "window_geometry": "1200x800+10+20",
            "window_state": "zoomed",
        },
        path,
    )

    assert load_interface_state(path) == {
        "game_name": "PokerTH",
        "decision_mode": "pokercharts",
        "hero_position": "CO",
        "window_geometry": "1200x800+10+20",
        "window_state": "zoomed",
    }


def test_select_initial_game_uses_cli_then_saved_then_default() -> None:
    profiles = ["PMU", "PokerTH"]

    assert select_initial_game("PMU", {"game_name": "PokerTH"}, profiles) == "PMU"
    assert select_initial_game(None, {"game_name": "PokerTH"}, profiles) == "PokerTH"
    assert select_initial_game(None, {"game_name": "Missing"}, profiles) == "PMU"


def test_select_initial_decision_mode_uses_explicit_cli_then_saved_then_legacy() -> None:
    assert select_initial_decision_mode("legacy", {"decision_mode": "pokermaster"}, cli_explicit=True) == "legacy"
    assert select_initial_decision_mode("legacy", {"decision_mode": "pokermaster"}, cli_explicit=False) == "pokermaster"
    assert select_initial_decision_mode("legacy", {"decision_mode": "pokercharts"}, cli_explicit=False) == "legacy"
    assert select_initial_decision_mode("legacy", {"decision_mode": "missing"}, cli_explicit=False) == "legacy"


def test_select_initial_hero_position_uses_explicit_cli_then_saved_then_button() -> None:
    assert select_initial_hero_position("UTG", {"hero_position": "CO"}, cli_explicit=True) == "UTG"
    assert select_initial_hero_position("BTN", {"hero_position": "CO"}, cli_explicit=False) == "CO"
    assert select_initial_hero_position("BTN", {"hero_position": "missing"}, cli_explicit=False) == "BTN"


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


def test_parse_args_defaults_to_legacy_decision_mode() -> None:
    args = parse_args([])

    assert args.decision_mode == "legacy"
    assert args.decision_mode_explicit is False
    assert args.hero_position == "BTN"
    assert args.hero_position_explicit is False


def test_parse_args_accepts_pokermaster_decision_mode() -> None:
    args = parse_args(["--decision-mode", "pokermaster"])

    assert args.decision_mode == "pokermaster"
    assert args.decision_mode_explicit is True


def test_parse_args_rejects_pokercharts_as_standalone_decision_mode() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--decision-mode", "pokercharts"])


def test_parse_args_rejects_range_analyzer_as_decision_mode() -> None:
    with pytest.raises(SystemExit):
        parse_args(["--decision-mode", "range_analyzer"])


def test_parse_args_accepts_equals_form_as_explicit_decision_mode() -> None:
    args = parse_args(["--decision-mode=pokermaster"])

    assert args.decision_mode == "pokermaster"
    assert args.decision_mode_explicit is True


def test_parse_args_accepts_hero_position() -> None:
    args = parse_args(["--hero-position", "CO"])

    assert args.hero_position == "CO"
    assert args.hero_position_explicit is True


def test_switch_decision_mode_replaces_current_decision_engine() -> None:
    app = App.__new__(App)
    app.game_name = "PMU"
    app.decision_mode = "legacy"
    app.var_decision_mode = _Var("pokermaster")
    app.controller = SimpleNamespace(decision=SimpleNamespace(config=SimpleNamespace(mode="legacy")))
    app.stop_scan = lambda: None
    app._save_interface_state = lambda: None

    App._switch_decision_mode(app)

    assert app.decision_mode == "pokermaster"
    assert app.controller.decision.config.mode == "pokermaster"


def test_switch_hero_position_updates_controller() -> None:
    calls = []
    app = App.__new__(App)
    app.game_name = "PMU"
    app.hero_position = "BTN"
    app.var_hero_position = _Var("CO")
    app.controller = SimpleNamespace(set_hero_position=lambda position: calls.append(position))
    app._save_interface_state = lambda: None

    App._switch_hero_position(app)

    assert app.hero_position == "CO"
    assert calls == ["CO"]


def test_save_interface_state_includes_decision_mode_and_hero_position(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
    app.var_game = _Var("PokerTH")
    app.game_name = "PMU"
    app.decision_mode = "pokermaster"
    app.hero_position = "CO"
    app.geometry = lambda: "1200x800+10+20"
    app.state = lambda: "normal"
    saved = []
    monkeypatch.setattr("launch.save_interface_state", lambda data: saved.append(data))

    App._save_interface_state(app)

    assert saved == [
        {
            "game_name": "PokerTH",
            "decision_mode": "pokermaster",
            "hero_position": "CO",
            "window_geometry": "1200x800+10+20",
            "window_state": "normal",
        }
    ]


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

    command = app._click_queue.get_nowait()
    assert command.click_box == (105, 210, 30, 40)
    assert command.decision_action == "CALL"
    assert command.raise_amount is None
    assert app._click_queue.empty()


def test_auto_click_stays_armed_after_queueing_target(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr("launch.time.monotonic", lambda: 100.0)

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

    assert app._click_queue.get_nowait().click_box == (105, 210, 30, 40)
    assert app._click_queue.empty()
    assert app.var_auto_click_target.get() is True


def test_auto_click_waits_after_activation_before_queueing(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
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
    app.controller = SimpleNamespace(
        last_view_state=state,
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
    app._auto_click_after_id = None
    now = [100.0]
    callbacks = []
    monkeypatch.setattr("launch.time.monotonic", lambda: now[0])
    app.after = lambda delay_ms, callback: callbacks.append((delay_ms, callback)) or f"after-{len(callbacks)}"
    app.after_cancel = lambda _after_id: None

    App._on_auto_click_option_changed(app)

    assert app._click_queue.empty()
    assert callbacks[0][0] == 1000
    assert app.var_auto_click_target.get() is True

    now[0] = 100.5
    App._maybe_queue_target_click(app, state)

    assert app._click_queue.empty()
    assert app.var_auto_click_target.get() is True

    now[0] = 101.1
    callbacks[-1][1]()

    command = app._click_queue.get_nowait()
    assert command.click_box == (105, 210, 30, 40)
    assert app.var_auto_click_target.get() is True


def test_auto_click_carries_raise_amount() -> None:
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
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=42,
        decision_action="RAISE",
        raise_amount=820.0,
        target_button={
            "label": "B1",
            "state": "relance",
            "bbox": [100, 200, 30, 40],
        },
    )

    App._maybe_queue_target_click(app, state)

    command = app._click_queue.get_nowait()
    assert command.click_box == (105, 210, 30, 40)
    assert command.game_name == "PokerTH"
    assert command.decision_action == "RAISE"
    assert command.raise_amount == 820.0
    assert command.runtime_offset == (5, 10)


def test_auto_click_blocks_fold_when_no_call_amount() -> None:
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
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=42,
        decision_action="FOLD",
        to_call=0.0,
        target_button={
            "label": "B1",
            "state": "fold",
            "bbox": [100, 200, 30, 40],
        },
    )

    App._maybe_queue_target_click(app, state)

    assert app._click_queue.empty()
    assert app.var_click_status.get() == "clic: fold bloque sans call"


def test_auto_click_queues_fold_when_call_amount_is_positive() -> None:
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

    fold_state = ControllerViewState(
        game_name="PokerTH",
        scan_count=1,
        scan_ok=True,
        scan_failures=0,
        hand_id=42,
        decision_action="FOLD",
        to_call=10.0,
        target_button={
            "label": "B3",
            "state": "fold",
            "bbox": [100, 200, 30, 40],
        },
    )

    App._maybe_queue_target_click(app, fold_state)

    command = app._click_queue.get_nowait()
    assert command.decision_action == "FOLD"
    assert command.click_box == (105, 210, 30, 40)
    assert app._click_queue.empty()
    assert app.var_auto_click_target.get() is True


def test_execute_target_action_enters_raise_amount_before_click(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
    calls = []
    app.controller = SimpleNamespace(
        last_view_state=ControllerViewState(
            game_name="PokerTH",
            scan_count=1,
            scan_ok=True,
            scan_failures=0,
            hand_id=42,
            street="TURN",
            decision_action="RAISE",
            raise_amount=820.0,
            target_button={
                "label": "B1",
                "state": "relance",
                "bbox": [5, 10, 30, 40],
            },
        ),
        game=SimpleNamespace(
            table=SimpleNamespace(
                scan=SimpleNamespace(runtime_region_offset=(5, 10)),
            ),
        ),
    )

    monkeypatch.setattr(
        "launch.enter_raise_amount_for_game",
        lambda game, amount, *, runtime_offset: calls.append(("type", game, amount, runtime_offset)) or "820",
    )
    app._left_click_box_center = lambda box: calls.append(("click", box))

    command = SimpleNamespace(
        click_box=(10, 20, 30, 40),
        game_name="PokerTH",
        decision_action="RAISE",
        raise_amount=820.0,
        runtime_offset=(5, 10),
        hand_id=42,
        street="TURN",
        target_button_label="B1",
        target_button_state="relance",
        queued_at=0.0,
    )

    App._execute_target_action(app, command)

    assert calls == [
        ("type", "PokerTH", 820.0, (5, 10)),
        ("click", (10, 20, 30, 40)),
    ]


def test_execute_target_action_skips_stale_command(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.__new__(App)
    calls = []
    app.controller = SimpleNamespace(
        last_view_state=ControllerViewState(
            game_name="PokerTH",
            scan_count=2,
            scan_ok=False,
            scan_failures=1,
            hand_id=42,
            street="TURN",
        ),
        game=SimpleNamespace(
            table=SimpleNamespace(
                scan=SimpleNamespace(runtime_region_offset=(5, 10)),
            ),
        ),
    )

    monkeypatch.setattr(
        "launch.enter_raise_amount_for_game",
        lambda *args, **kwargs: calls.append(("type", args, kwargs)) or "820",
    )
    app._left_click_box_center = lambda box: calls.append(("click", box))

    command = SimpleNamespace(
        click_box=(10, 20, 30, 40),
        game_name="PokerTH",
        decision_action="RAISE",
        raise_amount=820.0,
        runtime_offset=(5, 10),
        hand_id=42,
        street="TURN",
        target_button_label="B1",
        target_button_state="relance",
        queued_at=0.0,
    )

    App._execute_target_action(app, command)

    assert calls == []


def test_left_click_box_uses_arc_clicker_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr("personal_arc_click.click_xywh_box", fake_click_xywh_box)

    assert click_target_button_box((10, 20, 30, 40)) == "clicked"
    assert calls == [
        (
            (10, 20, 30, 40),
            {
                "button": "left",
                "target_point": (25, 40),
                "inner_box_scale": 0.92,
                "click_box_scale": 1.0,
                "click_on_enter": False,
                "delay_chance": 0.0,
                "pre_click_delay_min": 0.025,
                "pre_click_delay_max": 0.08,
                "min_duration": 0.04,
                "max_duration": 0.10,
                "spiral_radius": 5.0,
                "jitter": 0.6,
            },
        )
    ]


def test_launch_support_enter_raise_amount_uses_config_root(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_enter(game, amount, **kwargs):
        calls.append((game, amount, kwargs))
        return "20"

    monkeypatch.setattr("launch_support._enter_raise_amount_for_game", fake_enter)

    assert enter_raise_amount_for_game("PokerTH", 20, runtime_offset=(1, 2)) == "20"
    assert calls[0][0] == "PokerTH"
    assert calls[0][1] == 20
    assert calls[0][2]["runtime_offset"] == (1, 2)


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value
