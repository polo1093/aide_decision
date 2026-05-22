from __future__ import annotations

import argparse
import math
import random
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple


Point = Tuple[int, int]
Region = Tuple[int, int, int, int]
VALID_BUTTONS = {"left", "right"}
DEFAULT_ARC_SCALE = 0.83
DEFAULT_RETURN_ARC_SCALE = 0.43
__all__ = [
    "ArcClickResult",
    "click_point",
    "click_xywh_box",
    "click_zone",
    "moveTo",
    "move_to_point",
    "move_to_zone",
    "xywh_to_region",
]


@dataclass(frozen=True)
class ArcClickResult:
    """Resultat d'un clic par grand arc avec depassement."""

    start: Point
    target: Point
    overshoot: Point
    movement_region: Region
    button: str
    clicked: bool


def _pyautogui():
    import pyautogui

    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    pyautogui.FAILSAFE = True
    return pyautogui


def check_emergency_stop(pyautogui_module=None) -> None:
    pyautogui = pyautogui_module or _pyautogui()
    fail_safe_check = getattr(pyautogui, "_failSafeCheck", None)
    if fail_safe_check is not None:
        fail_safe_check()


def interruptible_sleep(seconds: float, *, step: float = 0.01, pyautogui_module=None) -> None:
    if seconds <= 0:
        return

    pyautogui = pyautogui_module or _pyautogui()
    end = time.perf_counter() + max(0.0, seconds)
    while True:
        check_emergency_stop(pyautogui)
        remaining = end - time.perf_counter()
        if remaining <= 0:
            return
        time.sleep(min(step, remaining))


def parse_region(value: str) -> Region:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must use x1,y1,x2,y2")
    try:
        return normalise_region(tuple(int(part) for part in parts))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_point(value: str) -> Point:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("point must use x,y")
    return int(parts[0]), int(parts[1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Personal fast arc click: overshoot target, return by a second arc, then click"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--region", required=True, type=parse_region)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--focus-wait", type=float, default=3.0)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--target-point", type=parse_point, default=None)
    parser.add_argument("--button", choices=sorted(VALID_BUTTONS), default="left")
    parser.add_argument("--min-duration", type=float, default=0.075)
    parser.add_argument("--max-duration", type=float, default=0.16)
    parser.add_argument("--arc-scale", type=float, default=DEFAULT_ARC_SCALE)
    parser.add_argument("--return-arc-scale", type=float, default=DEFAULT_RETURN_ARC_SCALE)
    parser.add_argument("--overshoot-min", type=float, default=20.0)
    parser.add_argument("--overshoot-max", type=float, default=90.0)
    parser.add_argument("--settle-min", type=float, default=0.010)
    parser.add_argument("--settle-max", type=float, default=0.040)
    return parser.parse_args()


def validate_button(button: str) -> str:
    if button not in VALID_BUTTONS:
        raise ValueError("button must be 'left' or 'right'")
    return button


def validate_options(
    *,
    min_duration: float,
    max_duration: float,
    arc_scale: float,
    return_arc_scale: float,
    overshoot_min: float,
    overshoot_max: float,
    settle_min: float,
    settle_max: float,
) -> None:
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("duration range is invalid")
    if arc_scale <= 0 or return_arc_scale <= 0:
        raise ValueError("arc scales must be positive")
    if overshoot_min < 0 or overshoot_max < overshoot_min:
        raise ValueError("overshoot range is invalid")
    if settle_min < 0 or settle_max < settle_min:
        raise ValueError("settle range is invalid")


def screen_region() -> Region:
    pyautogui = _pyautogui()
    width, height = pyautogui.size()
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


def scaled_region(region: Region, scale: float) -> Region:
    x1, y1, x2, y2 = normalise_region(region)
    if not 0.1 <= scale <= 1.0:
        raise ValueError("scale must be between 0.1 and 1.0")
    width = x2 - x1
    height = y2 - y1
    scaled_width = max(1, round(width * scale))
    scaled_height = max(1, round(height * scale))
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    sx1 = round(cx - scaled_width / 2.0)
    sy1 = round(cy - scaled_height / 2.0)
    return sx1, sy1, sx1 + scaled_width, sy1 + scaled_height


def clamp_point(point: tuple[float, float], region: Region, margin: int = 2) -> Point:
    x1, y1, x2, y2 = region
    max_margin = max(0, min((x2 - x1) // 2, (y2 - y1) // 2, margin))
    x = min(max(point[0], x1 + max_margin), x2 - max_margin)
    y = min(max(point[1], y1 + max_margin), y2 - max_margin)
    return round(x), round(y)


def random_target(region: Region, margin: int = 12) -> Point:
    x1, y1, x2, y2 = region
    max_margin = max(0, min((x2 - x1) // 2, (y2 - y1) // 2, margin))
    return (
        random.randint(x1 + max_margin, x2 - max_margin),
        random.randint(y1 + max_margin, y2 - max_margin),
    )


def ease_out(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def signed_short_delta(start_angle: float, end_angle: float) -> float:
    return (end_angle - start_angle + math.pi) % math.tau - math.pi


def arc_points(
    start: Point,
    end: Point,
    region: Region,
    *,
    duration: float,
    arc_scale: float,
    side: Optional[int] = None,
) -> Iterable[Point]:
    """Genere un arc de cercle dont le rayon est plus grand que l'ecran."""

    start = clamp_point(start, region)
    end = clamp_point(end, region)
    if start == end:
        yield end
        return

    x1, y1, x2, y2 = region
    screen_diagonal = max(1.0, math.hypot(x2 - x1, y2 - y1))
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    chord = max(1.0, math.hypot(dx, dy))
    nx = -dy / chord
    ny = dx / chord
    side = side if side in {-1, 1} else random.choice([-1, 1])

    mid_x = (start[0] + end[0]) / 2.0
    mid_y = (start[1] + end[1]) / 2.0
    # Plus arc_scale est bas, plus le centre du cercle se rapproche et plus la courbe se marque.
    center_offset = max(screen_diagonal * arc_scale, chord * 1.35)
    center_x = mid_x + nx * center_offset * side
    center_y = mid_y + ny * center_offset * side
    radius = math.hypot(start[0] - center_x, start[1] - center_y)

    start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
    end_angle = math.atan2(end[1] - center_y, end[0] - center_x)
    delta = signed_short_delta(start_angle, end_angle)
    steps = max(7, int(duration * random.uniform(115, 170)))
    previous: Optional[Point] = None

    for index in range(1, steps + 1):
        progress = index / steps
        eased = ease_out(progress)
        angle = start_angle + delta * eased
        drift = math.sin(progress * math.pi) * random.uniform(-0.35, 0.35)
        candidate = clamp_point(
            (
                center_x + math.cos(angle) * radius + drift,
                center_y + math.sin(angle) * radius - drift * 0.4,
            ),
            region,
        )
        if candidate != previous:
            previous = candidate
            yield candidate

    if previous != end:
        yield end


def choose_overshoot_point(
    start: Point,
    target: Point,
    region: Region,
    *,
    overshoot_min: float,
    overshoot_max: float,
) -> Point:
    """Choisit un point apres la cible, dans la direction du mouvement."""

    dx = target[0] - start[0]
    dy = target[1] - start[1]
    distance = math.hypot(dx, dy)
    if distance < 1.0:
        angle = random.uniform(0, math.tau)
        ux = math.cos(angle)
        uy = math.sin(angle)
    else:
        ux = dx / distance
        uy = dy / distance

    overshoot_distance = random.uniform(overshoot_min, overshoot_max)
    if distance >= 1.0:
        overshoot_distance = max(overshoot_distance, distance * random.uniform(0.10, 0.22))

    nx = -uy
    ny = ux
    lateral = random.uniform(-0.035, 0.035) * max(distance, overshoot_distance)
    candidate = clamp_point(
        (
            target[0] + ux * overshoot_distance + nx * lateral,
            target[1] + uy * overshoot_distance + ny * lateral,
        ),
        region,
    )

    if math.hypot(candidate[0] - target[0], candidate[1] - target[1]) >= 4.0:
        return candidate

    fallback = clamp_point(
        (
            target[0] + nx * max(overshoot_min, 10.0),
            target[1] + ny * max(overshoot_min, 10.0),
        ),
        region,
    )
    return fallback


def move_path(points: Iterable[Point], duration: float) -> None:
    points = list(points)
    if not points:
        return

    pyautogui = _pyautogui()
    started = time.perf_counter()
    planned_duration = max(0.0, duration)
    last_index = len(points) - 1

    for index, point in enumerate(points):
        check_emergency_stop(pyautogui)
        pyautogui.moveTo(point[0], point[1], duration=0)
        if index >= last_index or planned_duration <= 0:
            continue

        next_at = started + planned_duration * ((index + 1) / last_index)
        remaining = next_at - time.perf_counter()
        if remaining > 0:
            interruptible_sleep(remaining, step=0.001, pyautogui_module=pyautogui)


def move_to_point(
    point: Point,
    *,
    region: Optional[Region] = None,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
) -> tuple[Point, Point, Point]:
    """Deplace la souris en deux arcs: depassement, puis retour sur le point."""

    validate_options(
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
        settle_min=0.0,
        settle_max=0.0,
    )
    movement_region = region or screen_region()
    pyautogui = _pyautogui()
    start = clamp_point(pyautogui.position(), movement_region)
    target = clamp_point(point, movement_region)
    overshoot = choose_overshoot_point(
        start,
        target,
        movement_region,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
    )

    duration = random.uniform(min_duration, max_duration)
    first_duration = duration * random.uniform(0.56, 0.70)
    second_duration = max(0.01, duration - first_duration)
    first_side = random.choice([-1, 1])

    first_arc = list(
        arc_points(
            start,
            overshoot,
            movement_region,
            duration=first_duration,
            arc_scale=arc_scale,
            side=first_side,
        )
    )
    second_arc = list(
        arc_points(
            overshoot,
            target,
            movement_region,
            duration=second_duration,
            arc_scale=return_arc_scale,
            side=-first_side,
        )
    )
    move_path([*first_arc, *second_arc], duration)
    return start, target, overshoot


def move_to_zone(
    region: Region,
    *,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
) -> tuple[Point, Point, Point]:
    target = random_target(region)
    return move_to_point(
        target,
        region=region,
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
    )


def moveTo(
    point: Point,
    *,
    region: Optional[Region] = None,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
) -> Point:
    """Deplace la souris vers un point avec le mouvement en deux arcs, sans cliquer."""

    _start, target, _overshoot = move_to_point(
        point,
        region=region,
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
    )
    return target


def click_point(
    point: Point,
    *,
    button: str = "left",
    region: Optional[Region] = None,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
    settle_min: float = 0.010,
    settle_max: float = 0.040,
) -> ArcClickResult:
    """Clique un point precis avec un grand arc, depassement, retour precis."""

    validate_options(
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
        settle_min=settle_min,
        settle_max=settle_max,
    )
    button = validate_button(button)
    movement_region = region or screen_region()
    start, target, overshoot = move_to_point(
        point,
        region=movement_region,
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
    )
    interruptible_sleep(random.uniform(settle_min, settle_max), step=0.002)
    check_emergency_stop()
    pyautogui = _pyautogui()
    pyautogui.click(button=button)
    return ArcClickResult(
        start=start,
        target=target,
        overshoot=overshoot,
        movement_region=movement_region,
        button=button,
        clicked=True,
    )


def click_zone(
    *,
    region: Region,
    button: str = "left",
    target_point: Optional[Point] = None,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
    settle_min: float = 0.010,
    settle_max: float = 0.040,
) -> ArcClickResult:
    """Choisit un point dans la zone, puis appelle click_point(...)."""

    target = target_point if target_point is not None else random_target(region)
    return click_point(
        target,
        button=button,
        region=region,
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
        settle_min=settle_min,
        settle_max=settle_max,
    )


def click_xywh_box(
    box: tuple[int, int, int, int],
    *,
    button: str = "left",
    target_point: Optional[Point] = None,
    inner_box_scale: float = 0.92,
    click_box_scale: float = 1.00,
    delay_chance: float = 0.0,
    pre_click_delay_min: float = 0.010,
    pre_click_delay_max: float = 0.040,
    min_duration: float = 0.075,
    max_duration: float = 0.16,
    spiral_radius: float = 5.0,
    jitter: float = 0.6,
    click_on_enter: bool = False,
    arc_scale: float = DEFAULT_ARC_SCALE,
    return_arc_scale: float = DEFAULT_RETURN_ARC_SCALE,
    overshoot_min: float = 20.0,
    overshoot_max: float = 90.0,
) -> ArcClickResult:
    """Click an absolute screen box expressed as ``(x, y, width, height)``."""

    _ = delay_chance, spiral_radius, jitter, click_on_enter
    region = xywh_to_region(box)
    click_region = scaled_region(scaled_region(region, inner_box_scale), click_box_scale)
    target = clamp_point(target_point, click_region) if target_point is not None else random_target(click_region)
    return click_point(
        target,
        button=button,
        region=screen_region(),
        min_duration=min_duration,
        max_duration=max_duration,
        arc_scale=arc_scale,
        return_arc_scale=return_arc_scale,
        overshoot_min=overshoot_min,
        overshoot_max=overshoot_max,
        settle_min=pre_click_delay_min,
        settle_max=pre_click_delay_max,
    )


def run(args: argparse.Namespace) -> None:
    from tools.mouse_program_protocol import run_click_protocol

    if args.seed is not None:
        random.seed(args.seed)

    pyautogui = _pyautogui()
    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    pyautogui.FAILSAFE = True
    print(
        "Program: personal_arc_click | "
        f"clicks={args.count} | region={args.region} | "
        f"arc_scale={args.arc_scale:.2f} | return_arc_scale={args.return_arc_scale:.2f} | "
        f"overshoot={args.overshoot_min:.0f}-{args.overshoot_max:.0f}px | "
        "failsafe=screen-corner"
    )
    print(f"PyAutoGUI: pos={pyautogui.position()} size={pyautogui.size()}")

    def click_once(_index: int) -> ArcClickResult:
        check_emergency_stop()
        return click_zone(
            region=args.region,
            target_point=args.target_point,
            button=args.button,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            arc_scale=args.arc_scale,
            return_arc_scale=args.return_arc_scale,
            overshoot_min=args.overshoot_min,
            overshoot_max=args.overshoot_max,
            settle_min=args.settle_min,
            settle_max=args.settle_max,
        )

    def format_result(index: int, result: ArcClickResult) -> str:
        return (
            f"{index:02d} start={result.start} overshoot={result.overshoot} "
            f"target={result.target} button={result.button} clicked={result.clicked}"
        )

    run_click_protocol(
        count=args.count,
        base_url=args.base_url,
        session_id=args.session_id,
        focus_wait=args.focus_wait,
        click_once=click_once,
        format_result=format_result,
        fetch_telemetry_each_click=False,
    )


def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise SystemExit("--count must be >= 1")
    try:
        validate_options(
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            arc_scale=args.arc_scale,
            return_arc_scale=args.return_arc_scale,
            overshoot_min=args.overshoot_min,
            overshoot_max=args.overshoot_max,
            settle_min=args.settle_min,
            settle_max=args.settle_max,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    run(args)


if __name__ == "__main__":
    main()
