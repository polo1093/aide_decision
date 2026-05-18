#!/usr/bin/env python3
"""Extract full-screen frames from a calibration video at regular intervals."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time
from typing import Optional, Tuple

import cv2
from PIL import Image

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.services.game import Game  # type: ignore
from objet.utils.calibration import load_coordinates


def _auto_video(game_dir: Path) -> Optional[Path]:
    base = game_dir / "entrainement" / "cards_video"
    if base.is_file():
        return base
    if base.is_dir():
        for ext in (".avi", ".mp4", ".mkv", ".mov"):
            candidate = base / f"cards_video{ext}"
            if candidate.exists():
                return candidate
        for candidate in sorted(base.glob("*")):
            if candidate.suffix.lower() in {".avi", ".mp4", ".mkv", ".mov"}:
                return candidate
    for ext in (".avi", ".mp4", ".mkv", ".mov"):
        candidate = game_dir / "entrainement" / f"cards_video{ext}"
        if candidate.exists():
            return candidate
    return None


def _default_game_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "config" / "PMU",
        Path.cwd() / "config" / "PMU",
        Path.cwd().parent / "config" / "PMU",
    ]
    for candidate in candidates:
        if (candidate / "coordinates.json").exists():
            return candidate
    return candidates[0]


def _iter_time_step(cap: cv2.VideoCapture, seconds_step: float):
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0
    step_frames = max(1, int(round(fps * float(seconds_step))))
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step_frames == 0:
            yield index, frame
        index += 1


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "?"
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes:d}m{sec:02d}s"
    return f"{sec:d}s"


def _ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_table_capture(game_dir: Path) -> Tuple[dict, dict, dict]:
    regions, templates, table_capture = load_coordinates(game_dir / "coordinates.json")
    return regions, templates, table_capture


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Save full-screen frames from a calibration video")
    parser.add_argument(
        "--game-dir",
        default=str(_default_game_dir()),
        help="Path to the game directory (default: auto-detected config/<game>)",
    )
    parser.add_argument(
        "--video",
        help="Explicit video path; default: game_dir/entrainement/cards_video/cards_video.*",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between captures (default: 3.0)",
    )
    parser.add_argument(
        "--out",
        help="Output directory (default: game_dir/entrainement/screens)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, ...). Default: INFO",
    )
    parser.add_argument(
        "--progress-steps",
        type=int,
        default=20,
        help="Number of progress updates during extraction (default: 20)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("crop_video_frames")

    game_dir = Path(args.game_dir)
    out_dir = _ensure_output_dir(Path(args.out) if args.out else (game_dir / "entrainement" / "screens"))

    regions, templates, table_capture = _load_table_capture(game_dir)
    game = Game.for_script(Path(__file__).name)
    game.update_from_capture(
        table_capture=table_capture,
        regions={k: {"group": r.group, "top_left": r.top_left, "size": r.size} for k, r in regions.items()},
        templates=templates,
    )

    video_path = Path(args.video) if args.video else _auto_video(game_dir)
    if not video_path or not video_path.exists():
        raise SystemExit(
            f"ERROR: no video found. Put a file inside {game_dir/'entrainement'/'cards_video'} or pass --video"
        )

    logger.info("Using game_dir: %s", game_dir)
    logger.info("Using video:    %s", video_path)
    bounds = table_capture.get("bounds") if isinstance(table_capture, dict) else None
    if bounds:
        logger.info("Table bounds:  %s", bounds)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise SystemExit(f"ERROR: cannot open video: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0
    total_frames_raw = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step_frames = max(1, int(round(fps * float(args.interval))))
    expected_saves = ((total_frames_raw - 1) // step_frames + 1) if total_frames_raw > 0 else None
    duration = (total_frames_raw / fps) if total_frames_raw > 0 else None
    logger.info(
        "Video details: fps=%.2f, frames=%s, duration=%s, interval=%.2fs, step=%s frame(s)",
        fps,
        total_frames_raw if total_frames_raw > 0 else "?",
        _format_duration(duration),
        float(args.interval),
        step_frames,
    )
    if expected_saves is not None:
        logger.info("Expected output: about %s PNG frame(s)", expected_saves)

    saved = 0
    started = time.perf_counter()
    progress_steps = max(1, int(args.progress_steps))
    progress_every = max(1, (expected_saves or progress_steps) // progress_steps)
    for frame_index, frame_bgr in _iter_time_step(capture, seconds_step=float(args.interval)):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_img = Image.fromarray(frame_rgb).convert("RGBA")
        out_path = out_dir / f"frame_{frame_index:06d}.png"
        frame_img.save(out_path)
        saved += 1
        should_report = saved == 1 or saved % progress_every == 0
        if expected_saves is not None and saved >= expected_saves:
            should_report = True
        if should_report:
            elapsed = time.perf_counter() - started
            pct = (saved / expected_saves * 100.0) if expected_saves else 0.0
            eta = None
            if expected_saves and saved > 0:
                eta = elapsed * max(0, expected_saves - saved) / saved
            logger.info(
                "Progress: %s/%s saved (%.1f%%), source frame=%s/%s, elapsed=%s, ETA=%s, last=%s",
                saved,
                expected_saves if expected_saves is not None else "?",
                pct,
                frame_index,
                total_frames_raw if total_frames_raw > 0 else "?",
                _format_duration(elapsed),
                _format_duration(eta),
                out_path.name,
            )
        else:
            logger.debug("Saved %s", out_path.name)

    capture.release()
    logger.info("Extraction complete: %s frames saved in %s", saved, _format_duration(time.perf_counter() - started))
    print(f"Done. {saved} frames written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
