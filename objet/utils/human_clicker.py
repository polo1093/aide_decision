"""Human-like mouse movement and click helpers.

The public API works with absolute screen regions expressed as
``(x1, y1, x2, y2)``. Imports of pyautogui stay lazy so tests can import the
project without opening a GUI backend.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


Point = Tuple[int, int]
Region = Tuple[int, int, int, int]
VALID_BUTTONS = {"left", "right"}


@dataclass(frozen=True)
class ClickResult:
    """Result of a humanized click."""

    target: Point
    target_region: Region
    movement_region: Region
    click_region: Region
    button: str
    delayed: bool
    clicked: bool
    click_point: Optional[Point]


def _pyautogui():
    import pyautogui

    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    pyautogui.FAILSAFE = True
    return pyautogui


def _check_emergency_stop(pyautogui_module) -> None:
    """Let PyAutoGUI failsafe stop the worker when the mouse hits a corner."""

    fail_safe_check = getattr(pyautogui_module, "_failSafeCheck", None)
    if fail_safe_check is not None:
        fail_safe_check()


def _interruptible_sleep(seconds: float, *, step: float = 0.01) -> None:
    pyautogui_module = _pyautogui()
    end = time.perf_counter() + max(0.0, seconds)
    while True:
        _check_emergency_stop(pyautogui_module)
        remaining = end - time.perf_counter()
        if remaining <= 0:
            return
        time.sleep(min(step, remaining))


def validate_button(button: str) -> str:
    if button not in VALID_BUTTONS:
        raise ValueError("button must be 'left' or 'right'")
    return button


def validate_motion_options(
    *,
    min_duration: float,
    max_duration: float,
    delay_chance: float,
    delay_min: float,
    delay_max: float,
) -> None:
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("duration range is invalid")
    if not 0.0 <= delay_chance <= 1.0:
        raise ValueError("delay_chance must be between 0 and 1")
    if delay_min < 0 or delay_max < delay_min:
        raise ValueError("pre-click delay range is invalid")


def screen_region() -> Region:
    pyautogui_module = _pyautogui()
    width, height = pyautogui_module.size()
    return 0, 0, int(width), int(height)


def normalise_region(region: Region) -> Region:
    x1, y1, x2, y2 = (int(value) for value in region)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("region must be (x1, y1, x2, y2) with positive size")
    return x1, y1, x2, y2


def xywh_to_region(box: tuple[int, int, int, int]) -> Region:
    x, y, width, height = (int(value) for value in box)
    if width <= 0 or height <= 0:
        raise ValueError("box width and height must be positive")
    return x, y, x + width, y + height


def inner_box(region: Region, scale: float) -> Region:
    x1, y1, x2, y2 = normalise_region(region)
    width = x2 - x1
    height = y2 - y1
    inner_width = max(1, round(width * scale))
    inner_height = max(1, round(height * scale))
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    ix1 = round(cx - inner_width / 2.0)
    iy1 = round(cy - inner_height / 2.0)
    return ix1, iy1, ix1 + inner_width, iy1 + inner_height


def random_inner_box(region: Region, scale: float) -> Region:
    x1, y1, x2, y2 = normalise_region(region)
    width = x2 - x1
    height = y2 - y1
    box_width = max(1, min(width, round(width * scale)))
    box_height = max(1, min(height, round(height * scale)))
    bx1 = random.randint(x1, x2 - box_width)
    by1 = random.randint(y1, y2 - box_height)
    return bx1, by1, bx1 + box_width, by1 + box_height


def clamp_point(point: tuple[float, float], region: Region, margin: int = 8) -> Point:
    x1, y1, x2, y2 = normalise_region(region)
    max_margin = max(0, min((x2 - x1) // 2, (y2 - y1) // 2, margin))
    x = min(max(point[0], x1 + max_margin), x2 - max_margin)
    y = min(max(point[1], y1 + max_margin), y2 - max_margin)
    return round(x), round(y)


def point_in_region(point: Point, region: Region, margin: int = 0) -> bool:
    x1, y1, x2, y2 = normalise_region(region)
    return x1 + margin <= point[0] <= x2 - margin and y1 + margin <= point[1] <= y2 - margin


def random_target(region: Region) -> Point:
    x1, y1, x2, y2 = normalise_region(region)
    width = x2 - x1
    height = y2 - y1
    if random.random() < 0.65:
        cx = random.uniform(x1 + width * 0.18, x2 - width * 0.18)
        cy = random.uniform(y1 + height * 0.18, y2 - height * 0.18)
    else:
        margin = max(1, min(24, width // 4, height // 4))
        cx = random.uniform(x1 + margin, x2 - margin)
        cy = random.uniform(y1 + margin, y2 - margin)
    return clamp_point((cx, cy), region)


def choose_target(region: Region, target_point: Optional[Point]) -> Point:
    if target_point is not None:
        return clamp_point(target_point, region)
    return random_target(region)


def cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> tuple[float, float]:
    u = 1.0 - t
    x = (u**3 * p0[0]) + (3 * u**2 * t * p1[0]) + (3 * u * t**2 * p2[0]) + (t**3 * p3[0])
    y = (u**3 * p0[1]) + (3 * u**2 * t * p1[1]) + (3 * u * t**2 * p2[1]) + (t**3 * p3[1])
    return x, y


def ease_in_out(t: float) -> float:
    return 0.5 - (math.cos(math.pi * t) / 2.0)


def control_points(start: Point, end: Point, region: Region) -> tuple[Point, Point]:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    distance = max(1.0, math.hypot(dx, dy))
    nx = -dy / distance
    ny = dx / distance
    bend = random.uniform(-0.22, 0.22) * distance
    p1 = (
        sx + dx * random.uniform(0.25, 0.45) + nx * bend,
        sy + dy * random.uniform(0.15, 0.35) + ny * bend,
    )
    p2 = (
        sx + dx * random.uniform(0.58, 0.82) - nx * bend * 0.55,
        sy + dy * random.uniform(0.62, 0.90) - ny * bend * 0.55,
    )
    return clamp_point(p1, region), clamp_point(p2, region)


def path_to_target(start: Point, end: Point, region: Region, duration: float, spiral_radius: float) -> Iterable[Point]:
    start = clamp_point(start, region)
    end = clamp_point(end, region)
    p1, p2 = control_points(start, end, region)
    steps = max(12, int(duration * random.uniform(44, 62)))
    previous: Optional[Point] = None
    spiral_turns = random.uniform(2.0, 3.4)
    noise_phase = random.uniform(0.0, math.tau)
    noise_amplitude = random.uniform(0.02, 0.12)

    for index in range(steps):
        progress = index / max(1, steps - 1)
        eased = ease_in_out(progress)
        point = cubic_bezier(start, p1, p2, end, eased)

        if progress > 0.82:
            settle = min(1.0, max(0.0, (progress - 0.82) / 0.18))
            radius = spiral_radius * (1.0 - settle) ** 1.7
            angle = settle * spiral_turns * math.pi
            point = (
                point[0] + math.cos(angle) * radius,
                point[1] + math.sin(angle) * radius * 0.72,
            )

        noise = (1.0 - progress) * math.sin((progress * math.tau) + noise_phase) * noise_amplitude
        candidate = clamp_point((point[0] + noise, point[1] - noise * 0.6), region)
        if candidate != previous:
            previous = candidate
            yield candidate


def move_path(points: Iterable[Point], duration: float) -> None:
    pyautogui_module = _pyautogui()
    points = list(points)
    if not points:
        return
    base_sleep = duration / len(points)
    for point in points:
        _check_emergency_stop(pyautogui_module)
        pyautogui_module.moveTo(point[0], point[1], duration=max(0.001, base_sleep * 0.35))
        _interruptible_sleep(max(0.0005, base_sleep * random.uniform(0.02, 0.10)), step=0.002)


def move_path_click_on_enter(
    points: Iterable[Point],
    duration: float,
    click_region: Region,
    *,
    button: str,
    hold_min: float,
    hold_max: float,
    delay_chance: float,
) -> tuple[bool, bool, Optional[Point]]:
    pyautogui_module = _pyautogui()
    button = validate_button(button)
    points = list(points)
    if not points:
        return False, False, None

    clicked = False
    delayed = False
    click_point: Optional[Point] = None
    base_sleep = duration / len(points)
    click_margin = max(0, min((click_region[2] - click_region[0]) // 5, (click_region[3] - click_region[1]) // 5, 24))

    for point in points:
        _check_emergency_stop(pyautogui_module)
        pyautogui_module.moveTo(point[0], point[1], duration=max(0.002, base_sleep * 0.45))
        if not clicked and point_in_region(point, click_region, margin=click_margin):
            delayed = random.random() < delay_chance
            if delayed:
                _interruptible_sleep(random.uniform(hold_min, hold_max), step=0.002)
            _check_emergency_stop(pyautogui_module)
            pyautogui_module.mouseDown(button=button)
            _interruptible_sleep(random.uniform(hold_min, hold_max), step=0.002)
            _check_emergency_stop(pyautogui_module)
            pyautogui_module.mouseUp(button=button)
            clicked = True
            click_point = point
            return clicked, delayed, click_point
        _interruptible_sleep(max(0.001, base_sleep * random.uniform(0.04, 0.16)), step=0.002)

    return clicked, delayed, click_point


def move_to_point(
    point: Point,
    *,
    region: Optional[Region] = None,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
) -> Point:
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("duration range is invalid")
    pyautogui_module = _pyautogui()
    movement_region = normalise_region(region or screen_region())
    target = clamp_point(point, movement_region)
    start = clamp_point(pyautogui_module.position(), movement_region)
    duration = random.uniform(min_duration, max_duration)
    move_path(path_to_target(start, target, movement_region, duration, spiral_radius), duration)
    return target


def moveTo(
    point: Point,
    *,
    region: Optional[Region] = None,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
) -> Point:
    return move_to_point(
        point,
        region=region,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
    )


def move_to_zone(
    region: Region,
    *,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
) -> Point:
    target = random_target(region)
    return move_to_point(
        target,
        region=region,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
    )


def moveToZone(
    region: Region,
    *,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
) -> Point:
    return move_to_zone(
        region,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
    )


def moveTozone(
    region: Region,
    *,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
) -> Point:
    return moveToZone(
        region,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
    )


def settle_and_click(
    target: Point,
    region: Region,
    jitter: float,
    delay_chance: float,
    delay_min: float,
    delay_max: float,
    button: str = "left",
) -> bool:
    pyautogui_module = _pyautogui()
    button = validate_button(button)
    loops = random.randint(1, 3)
    for _ in range(loops):
        _check_emergency_stop(pyautogui_module)
        jx = random.uniform(-jitter, jitter) * 0.45
        jy = random.uniform(-jitter, jitter) * 0.45
        point = clamp_point((target[0] + jx, target[1] + jy), region)
        pyautogui_module.moveTo(point[0], point[1], duration=random.uniform(0.035, 0.09))
        _interruptible_sleep(random.uniform(0.02, 0.075), step=0.01)

    used_delay = random.random() < delay_chance
    if used_delay:
        _interruptible_sleep(random.uniform(delay_min, delay_max), step=0.01)

    _check_emergency_stop(pyautogui_module)
    pyautogui_module.click(button=button)
    return used_delay


def click_point(
    point: Point,
    *,
    button: str = "left",
    region: Optional[Region] = None,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
    jitter: float = 1.5,
    delay_chance: float = 0.0,
    pre_click_delay_min: float = 0.04,
    pre_click_delay_max: float = 0.18,
) -> bool:
    validate_motion_options(
        min_duration=min_duration,
        max_duration=max_duration,
        delay_chance=delay_chance,
        delay_min=pre_click_delay_min,
        delay_max=pre_click_delay_max,
    )
    button = validate_button(button)
    movement_region = normalise_region(region or screen_region())
    target = move_to_point(
        point,
        region=movement_region,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
    )
    return settle_and_click(
        target,
        movement_region,
        jitter,
        delay_chance,
        pre_click_delay_min,
        pre_click_delay_max,
        button,
    )


def click_zone(
    *,
    region: Region,
    target_point: Optional[Point] = None,
    button: str = "left",
    inner_box_scale: float = 0.70,
    click_box_scale: float = 0.35,
    delay_chance: float = 0.0,
    pre_click_delay_min: float = 0.04,
    pre_click_delay_max: float = 0.18,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
    jitter: float = 1.5,
    click_on_enter: bool = True,
) -> ClickResult:
    if not 0.1 <= inner_box_scale <= 1.0:
        raise ValueError("inner_box_scale must be between 0.1 and 1.0")
    if not 0.2 <= click_box_scale <= 1.0:
        raise ValueError("click_box_scale must be between 0.2 and 1.0")
    validate_motion_options(
        min_duration=min_duration,
        max_duration=max_duration,
        delay_chance=delay_chance,
        delay_min=pre_click_delay_min,
        delay_max=pre_click_delay_max,
    )
    pyautogui_module = _pyautogui()
    button = validate_button(button)
    region = normalise_region(region)
    movement_region = random_inner_box(region, inner_box_scale)
    click_region = random_inner_box(movement_region, click_box_scale)
    target = choose_target(click_region, target_point)
    start = clamp_point(pyautogui_module.position(), movement_region)
    duration = random.uniform(min_duration, max_duration)

    if click_on_enter:
        clicked, delayed, active_click_point = move_path_click_on_enter(
            path_to_target(start, target, movement_region, duration, spiral_radius),
            duration,
            click_region,
            button=button,
            hold_min=pre_click_delay_min,
            hold_max=pre_click_delay_max,
            delay_chance=delay_chance,
        )
    else:
        move_path(path_to_target(start, target, movement_region, duration, spiral_radius), duration)
        clicked = False
        delayed = False
        active_click_point = None

    if not clicked:
        delayed = settle_and_click(
            target,
            movement_region,
            jitter,
            delay_chance,
            pre_click_delay_min,
            pre_click_delay_max,
            button,
        )
        clicked = True
        active_click_point = target

    return ClickResult(
        target=target,
        target_region=click_region,
        movement_region=movement_region,
        click_region=click_region,
        button=button,
        delayed=delayed,
        clicked=clicked,
        click_point=active_click_point,
    )


def click_xywh_box(
    box: tuple[int, int, int, int],
    *,
    button: str = "left",
    target_point: Optional[Point] = None,
    inner_box_scale: float = 0.92,
    click_box_scale: float = 0.50,
    delay_chance: float = 0.0,
    pre_click_delay_min: float = 0.04,
    pre_click_delay_max: float = 0.18,
    min_duration: float = 0.06,
    max_duration: float = 0.14,
    spiral_radius: float = 10.0,
    jitter: float = 1.5,
    click_on_enter: bool = True,
) -> ClickResult:
    """Click inside an absolute screen box expressed as ``(x, y, width, height)``."""

    return click_zone(
        region=xywh_to_region(box),
        target_point=target_point,
        button=button,
        inner_box_scale=inner_box_scale,
        click_box_scale=click_box_scale,
        delay_chance=delay_chance,
        pre_click_delay_min=pre_click_delay_min,
        pre_click_delay_max=pre_click_delay_max,
        min_duration=min_duration,
        max_duration=max_duration,
        spiral_radius=spiral_radius,
        jitter=jitter,
        click_on_enter=click_on_enter,
    )


adaptive_spiral_human_plus_click = click_zone


__all__ = [
    "ClickResult",
    "click_point",
    "click_xywh_box",
    "click_zone",
    "moveTo",
    "moveToZone",
    "moveTozone",
    "move_to_point",
    "move_to_zone",
    "xywh_to_region",
]
