"""Tests for software-specific action connectors."""

from __future__ import annotations

import json
from pathlib import Path

from objet.services.action_connector import ActionConnector, enter_raise_amount_for_game, load_action_connector


class FakeKeyboard:
    def __init__(self) -> None:
        self.calls = []

    def press(self, key: str) -> None:
        self.calls.append(("press", key))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey", keys))


def test_missing_action_connector_is_disabled(tmp_path: Path) -> None:
    connector = load_action_connector("PokerTH", config_root=tmp_path)

    assert connector.enabled is False
    assert connector.enter_raise_amount(20, keyboard=FakeKeyboard()) is None


def test_connector_formats_integer_chip_amounts_for_numpad() -> None:
    keyboard = FakeKeyboard()
    focus_calls = []
    connector = ActionConnector(
        game_name="PokerTH",
        enabled=True,
        raise_amount_enabled=True,
        input_mode="numpad",
        round_to=0,
        clear_keys=("ctrl+a", "backspace"),
        press_interval=0.0,
        focus_before_typing=True,
        focus_box=(100, 200, 30, 40),
    )

    text = connector.enter_raise_amount(
        820.4,
        runtime_offset=(5, -10),
        keyboard=keyboard,
        focus_clicker=focus_calls.append,
        sleep=lambda _seconds: None,
    )

    assert text == "820"
    assert focus_calls == [(105, 190, 30, 40)]
    assert keyboard.calls == [
        ("hotkey", ("ctrl", "a")),
        ("press", "backspace"),
        ("press", "num8"),
        ("press", "num2"),
        ("press", "num0"),
    ]


def test_enter_raise_amount_for_game_loads_profile_config(tmp_path: Path) -> None:
    game_dir = tmp_path / "PokerTH"
    game_dir.mkdir()
    (game_dir / "action_connector.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "raise_amount": {
                    "enabled": True,
                    "input_mode": "numpad",
                    "press_interval": 0,
                    "format": {"round_to": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    keyboard = FakeKeyboard()

    text = enter_raise_amount_for_game(
        "PokerTH",
        15.8,
        config_root=tmp_path,
        keyboard=keyboard,
        sleep=lambda _seconds: None,
    )

    assert text == "16"
    assert keyboard.calls == [("press", "num1"), ("press", "num6")]
