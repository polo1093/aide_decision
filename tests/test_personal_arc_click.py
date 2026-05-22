from __future__ import annotations

import pytest

import personal_arc_click


class _FakePyAutoGui:
    def __init__(self) -> None:
        self.moves: list[tuple[int, int, float]] = []
        self.PAUSE = 0
        self.MINIMUM_DURATION = 0
        self.MINIMUM_SLEEP = 0
        self.FAILSAFE = True

    def _failSafeCheck(self) -> None:
        return None

    def moveTo(self, x: int, y: int, duration: float = 0) -> None:
        self.moves.append((x, y, duration))


def test_move_path_uses_wall_clock_budget_without_pyautogui_tween(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_pyautogui = _FakePyAutoGui()
    clock = {"now": 0.0}

    def fake_sleep(seconds: float, **_kwargs: object) -> None:
        clock["now"] += max(0.0, seconds)

    monkeypatch.setattr(personal_arc_click, "_pyautogui", lambda: fake_pyautogui)
    monkeypatch.setattr(personal_arc_click.time, "perf_counter", lambda: clock["now"])
    monkeypatch.setattr(personal_arc_click, "interruptible_sleep", fake_sleep)

    personal_arc_click.move_path([(10, 20), (30, 40), (50, 60)], 0.12)

    assert fake_pyautogui.moves == [(10, 20, 0), (30, 40, 0), (50, 60, 0)]
    assert clock["now"] == pytest.approx(0.12)
