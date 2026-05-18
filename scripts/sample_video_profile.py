#!/usr/bin/env python3
"""Extract representative table frames and a montage from a profile video."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image, ImageDraw

from profile_common import crop_to_capture, first_video, game_dir_for, video_metadata
from objet.utils.calibration import load_coordinates


def _frame_indices(total_frames: int, count: int, explicit: Optional[str]) -> list[int]:
    if explicit:
        return [int(part.strip()) for part in explicit.split(",") if part.strip()]
    if total_frames <= 0:
        return [0]
    if count <= 1:
        return [0]
    # Some codecs report the last frame as seekable even when OpenCV cannot
    # decode it reliably, so keep one frame of margin.
    last = max(0, total_frames - 2)
    return sorted({round(i * last / (count - 1)) for i in range(count)})


def _make_montage(frames: list[tuple[int, Image.Image]], thumb_width: int = 512, cols: int = 3) -> Image.Image:
    thumbs: list[Image.Image] = []
    for frame_index, image in frames:
        scale = thumb_width / image.width
        thumb = image.resize((thumb_width, max(1, round(image.height * scale))))
        draw = ImageDraw.Draw(thumb)
        draw.rectangle((0, 0, 95, 18), fill=(0, 0, 0))
        draw.text((4, 3), f"frame {frame_index}", fill=(255, 255, 255))
        thumbs.append(thumb)

    if not thumbs:
        return Image.new("RGB", (thumb_width, 1), (20, 20, 20))

    rows = (len(thumbs) + cols - 1) // cols
    thumb_height = max(thumb.height for thumb in thumbs)
    montage = Image.new("RGB", (cols * thumb_width, rows * thumb_height), (20, 20, 20))
    for index, thumb in enumerate(thumbs):
        montage.paste(thumb, ((index % cols) * thumb_width, (index // cols) * thumb_height))
    return montage


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sample a video into cropped profile frames.")
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--video", help="Video path; defaults to first video found in profile directory")
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--indices", help="Comma-separated frame indices; overrides --count")
    parser.add_argument("--out-dir", help="Output directory")
    parser.add_argument("--full-screen", action="store_true", help="Save full frames instead of table crop")
    args = parser.parse_args(argv)

    game_dir = game_dir_for(args.game, args.game_dir)
    video_path = Path(args.video) if args.video else first_video(game_dir)
    if video_path is None:
        raise SystemExit(f"ERROR: no video found in {game_dir}")

    meta = video_metadata(video_path)
    total_frames = int(meta["frames"])
    indices = _frame_indices(total_frames, max(1, int(args.count)), args.indices)
    out_dir = Path(args.out_dir) if args.out_dir else game_dir / "entrainement" / "profile_samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    table_capture = {}
    coord_path = game_dir / "coordinates.json"
    if coord_path.exists() and not args.full_screen:
        _regions, _templates, table_capture = load_coordinates(coord_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open video: {video_path}")

    saved: list[tuple[int, Image.Image]] = []
    try:
        for frame_index in indices:
            actual_index = int(frame_index)
            frame = None
            ok = False
            while actual_index >= 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, actual_index)
                ok, frame = cap.read()
                if ok:
                    break
                actual_index -= 1
            if not ok or frame is None:
                print(f"WARN: cannot read frame {frame_index}")
                continue
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGB")
            if table_capture and not args.full_screen:
                image = crop_to_capture(image, table_capture)
            out_path = out_dir / f"frame_{actual_index:06d}.png"
            image.save(out_path)
            saved.append((actual_index, image))
    finally:
        cap.release()

    montage = _make_montage(saved)
    montage_path = out_dir / "montage.jpg"
    montage.save(montage_path, quality=90)

    print("video:", video_path)
    print("metadata:", meta)
    print("saved:", len(saved), "frames to", out_dir)
    print("montage:", montage_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
