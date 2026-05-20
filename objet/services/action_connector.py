"""Configurable action connector for software-specific table controls."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Mapping, Optional, Protocol

from objet.utils.logging_config import get_logger


LOGGER = get_logger(__name__)
CONNECTOR_FILENAME = "action_connector.json"
DEFAULT_NUMPAD_KEYS = {
    "0": "num0",
    "1": "num1",
    "2": "num2",
    "3": "num3",
    "4": "num4",
    "5": "num5",
    "6": "num6",
    "7": "num7",
    "8": "num8",
    "9": "num9",
    ".": "decimal",
    ",": "decimal",
    "-": "subtract",
}


class KeyboardLike(Protocol):
    def press(self, key: str) -> None: ...

    def hotkey(self, *keys: str) -> None: ...


@dataclass(frozen=True)
class ActionConnector:
    """Describes how to enter an action amount for one game profile."""

    game_name: str
    enabled: bool = False
    raise_amount_enabled: bool = False
    input_mode: str = "numpad"
    round_to: int = 0
    decimal_separator: str = "."
    trim_trailing_zeros: bool = True
    clear_keys: tuple[str, ...] = ()
    key_map: Mapping[str, str] = None
    press_interval: float = 0.015
    focus_box: Optional[tuple[int, int, int, int]] = None
    focus_before_typing: bool = False

    def format_raise_amount(self, amount: object) -> Optional[str]:
        number = _as_float(amount)
        if number is None or number <= 0:
            return None

        round_to = max(0, int(self.round_to))
        if round_to == 0:
            text = str(int(round(number)))
        else:
            text = f"{number:.{round_to}f}"
            if self.trim_trailing_zeros:
                text = text.rstrip("0").rstrip(".")
        if self.decimal_separator != ".":
            text = text.replace(".", self.decimal_separator)
        return text or None

    def enter_raise_amount(
        self,
        amount: object,
        *,
        runtime_offset: tuple[int, int] = (0, 0),
        keyboard: Optional[KeyboardLike] = None,
        focus_clicker=None,
        sleep=None,
    ) -> Optional[str]:
        """Type the raise amount using this profile's configured input method."""

        if not self.enabled or not self.raise_amount_enabled:
            return None

        text = self.format_raise_amount(amount)
        if not text:
            return None

        keyboard = keyboard if keyboard is not None else _pyautogui()
        sleep = sleep if sleep is not None else time.sleep

        if self.focus_before_typing and self.focus_box is not None:
            clicker = focus_clicker if focus_clicker is not None else _click_xywh_box
            clicker(_offset_box(self.focus_box, runtime_offset))

        for key in self.clear_keys:
            _press_key(keyboard, key)
            sleep(self.press_interval)

        for char in text:
            _press_key(keyboard, self._key_for_char(char))
            sleep(self.press_interval)

        LOGGER.info("raise_amount_typed game=%s amount=%s text=%s", self.game_name, amount, text)
        return text

    def _key_for_char(self, char: str) -> str:
        if self.input_mode == "numpad":
            key_map = dict(DEFAULT_NUMPAD_KEYS)
            if self.key_map:
                key_map.update({str(key): str(value) for key, value in self.key_map.items()})
            return key_map.get(char, char)
        return char


def load_action_connector(
    game_name: str,
    *,
    config_root: Path | str = Path("config"),
) -> ActionConnector:
    """Load the action connector for a game profile, disabled when absent."""

    game = str(game_name).strip()
    game_dir = Path(config_root) / game
    path = game_dir / CONNECTOR_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ActionConnector(game_name=game)
    except Exception as exc:
        LOGGER.warning("action_connector_illisible path=%s error=%s", path, exc)
        return ActionConnector(game_name=game)

    if not isinstance(payload, dict):
        return ActionConnector(game_name=game)

    raise_amount = payload.get("raise_amount", {})
    if not isinstance(raise_amount, dict):
        raise_amount = {}

    formatting = raise_amount.get("format", {})
    if not isinstance(formatting, dict):
        formatting = {}

    focus = raise_amount.get("focus_before_typing", {})
    if not isinstance(focus, dict):
        focus = {}

    key_map = raise_amount.get("key_map", {})
    if not isinstance(key_map, dict):
        key_map = {}

    return ActionConnector(
        game_name=game,
        enabled=bool(payload.get("enabled", False)),
        raise_amount_enabled=bool(raise_amount.get("enabled", False)),
        input_mode=str(raise_amount.get("input_mode", "numpad")),
        round_to=_int_value(formatting.get("round_to"), 0),
        decimal_separator=str(formatting.get("decimal_separator", "."))[:1] or ".",
        trim_trailing_zeros=bool(formatting.get("trim_trailing_zeros", True)),
        clear_keys=tuple(str(key) for key in raise_amount.get("clear_keys", []) if key),
        key_map=key_map,
        press_interval=max(0.0, _float_value(raise_amount.get("press_interval"), 0.015)),
        focus_box=_parse_box(focus.get("box")),
        focus_before_typing=bool(focus.get("enabled", False)),
    )


def enter_raise_amount_for_game(
    game_name: str,
    amount: object,
    *,
    config_root: Path | str = Path("config"),
    runtime_offset: tuple[int, int] = (0, 0),
    keyboard: Optional[KeyboardLike] = None,
    focus_clicker=None,
    sleep=None,
) -> Optional[str]:
    connector = load_action_connector(game_name, config_root=config_root)
    return connector.enter_raise_amount(
        amount,
        runtime_offset=runtime_offset,
        keyboard=keyboard,
        focus_clicker=focus_clicker,
        sleep=sleep,
    )


def _pyautogui():
    import pyautogui

    pyautogui.PAUSE = 0
    return pyautogui


def _click_xywh_box(box: tuple[int, int, int, int]):
    from objet.utils.human_clicker import click_xywh_box

    return click_xywh_box(
        box,
        button="left",
        inner_box_scale=0.85,
        click_box_scale=0.60,
        delay_chance=0.0,
        pre_click_delay_min=0.02,
        pre_click_delay_max=0.06,
        min_duration=0.035,
        max_duration=0.09,
        spiral_radius=7.0,
        jitter=1.0,
    )


def _press_key(keyboard: KeyboardLike, key: str) -> None:
    keys = [part.strip() for part in str(key).split("+") if part.strip()]
    if len(keys) > 1:
        keyboard.hotkey(*keys)
        return
    if keys:
        keyboard.press(keys[0])


def _parse_box(value: object) -> Optional[tuple[int, int, int, int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(round(float(part))) for part in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _offset_box(box: tuple[int, int, int, int], offset: tuple[int, int]) -> tuple[int, int, int, int]:
    dx, dy = offset
    x, y, width, height = box
    return x + int(dx), y + int(dy), width, height


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_value(value: object, default: float) -> float:
    number = _as_float(value)
    return default if number is None else number


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "ActionConnector",
    "CONNECTOR_FILENAME",
    "enter_raise_amount_for_game",
    "load_action_connector",
]
