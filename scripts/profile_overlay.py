#!/usr/bin/env python3
"""Draw a visual overlay of profile regions on a table capture."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from PIL import Image

from profile_common import crop_to_capture, draw_regions, first_existing, game_dir_for, IMAGE_EXTS
from objet.utils.calibration import load_coordinates


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a debug overlay for config/<game>/coordinates.json")
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--image", help="Full-screen or already-cropped image to draw on")
    parser.add_argument("--out", help="Output PNG path")
    parser.add_argument("--no-labels", action="store_true", help="Draw boxes without region names")
    args = parser.parse_args(argv)

    game_dir = game_dir_for(args.game, args.game_dir)
    coord_path = game_dir / "coordinates.json"
    image_path = Path(args.image) if args.image else first_existing(
        game_dir,
        ("test_crop_result", "test_table", "test_crop", "test_screen", "test_fullscreen"),
        IMAGE_EXTS,
    )
    if image_path is None:
        raise SystemExit(f"ERROR: no image found for {game_dir}")

    regions, _templates, table_capture = load_coordinates(coord_path)
    image = Image.open(image_path).convert("RGB")
    table_image = crop_to_capture(image, table_capture)
    overlay = draw_regions(table_image, regions, table_capture, labels=not args.no_labels)

    out_path = Path(args.out) if args.out else game_dir / "debug_overlay.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(out_path)
    print("image:", image_path)
    print("regions:", len(regions))
    print("wrote:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
