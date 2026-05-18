#!/usr/bin/env python3
"""Validate a game profile and emit a concise report."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from PIL import Image

from profile_common import (
    ACTION_TEMPLATE_NAMES,
    IMAGE_EXTS,
    crop_to_capture,
    draw_regions,
    first_existing,
    game_dir_for,
    infer_table_capture,
)
from objet.entities.buttons import Buttons
from objet.entities.card import CardsState
from objet.entities.player import Players
from objet.services.table import Table
from objet.utils.calibration import collect_card_patches, load_coordinates, table_capture_origin


def _region_inside_capture(region, table_capture) -> bool:
    bounds = table_capture.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        return True
    x1, y1, x2, y2 = [int(v) for v in bounds]
    rx, ry = region.top_left
    rw, rh = region.size
    return x1 <= rx and y1 <= ry and rx + rw <= x2 and ry + rh <= y2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate config/<game> profile files and coordinates.")
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--overlay", action="store_true", help="Write validation_overlay.png")
    parser.add_argument("--image", help="Image used for overlay/card-presence checks")
    args = parser.parse_args(argv)

    game_dir = game_dir_for(args.game, args.game_dir)
    coord_path = game_dir / "coordinates.json"
    errors: list[str] = []
    warnings: list[str] = []

    if not coord_path.exists():
        raise SystemExit(f"ERROR: missing {coord_path}")

    try:
        regions, templates, table_capture = load_coordinates(coord_path)
    except Exception as exc:
        raise SystemExit(f"ERROR: cannot load {coord_path}: {exc}") from exc

    required_regions = [
        "pot",
        "fond",
        "button_1",
        "button_2",
        "button_3",
        "player_state_me",
        *(f"player_card_{idx}_{slot}" for idx in (1, 2) for slot in ("number", "symbol")),
        *(f"board_card_{idx}_{slot}" for idx in range(1, 6) for slot in ("number", "symbol")),
        *(f"player_money_J{idx}" for idx in range(1, 6)),
    ]
    for key in required_regions:
        if key not in regions:
            errors.append(f"missing region: {key}")

    for key, region in regions.items():
        if region.size[0] <= 0 or region.size[1] <= 0:
            errors.append(f"invalid size for region: {key} -> {region.size}")
        if not _region_inside_capture(region, table_capture):
            warnings.append(f"region outside table_capture bounds: {key} top_left={region.top_left} size={region.size}")

    for name in ACTION_TEMPLATE_NAMES:
        if not (game_dir / name).exists():
            warnings.append(f"missing action template: {name}")

    try:
        CardsState(coord_path=coord_path)
        Players(coord_path=coord_path)
        Buttons(coord_path=coord_path)
        Table(coord_path=coord_path)
    except Exception as exc:
        errors.append(f"profile object construction failed: {type(exc).__name__}: {exc}")

    try:
        inferred_capture, source = infer_table_capture(game_dir)
        if table_capture.get("size") != inferred_capture["size"]:
            warnings.append(f"table_capture.size differs from inferred: {table_capture.get('size')} != {inferred_capture['size']}")
        if table_capture.get("ref_offset") != inferred_capture["ref_offset"]:
            warnings.append(
                f"table_capture.ref_offset differs from inferred: {table_capture.get('ref_offset')} != {inferred_capture['ref_offset']}"
            )
        if table_capture.get("origin") != inferred_capture["origin"]:
            warnings.append(f"table_capture.origin differs from inferred: {table_capture.get('origin')} != {inferred_capture['origin']}")
        print("geometry_source:", source)
    except Exception as exc:
        warnings.append(f"geometry inference skipped: {type(exc).__name__}: {exc}")

    image_path = Path(args.image) if args.image else first_existing(
        game_dir,
        ("test_crop_result", "test_table", "test_crop", "test_screen", "test_fullscreen"),
        IMAGE_EXTS,
    )
    if image_path and image_path.exists():
        image = Image.open(image_path).convert("RGB")
        table_image = crop_to_capture(image, table_capture)
        patches = collect_card_patches(table_image, regions, table_capture=table_capture, pad=0)
        visible = []
        from objet.scanner.cards_recognition import is_card_present

        for key, patch in sorted(patches.items()):
            if is_card_present(patch.number, threshold=220):
                visible.append(key)
        print("card_regions:", len(patches), "visible_guess:", ", ".join(visible) if visible else "none")
        if args.overlay:
            overlay = draw_regions(table_image, regions, table_capture, labels=True)
            overlay_path = game_dir / "validation_overlay.png"
            overlay.save(overlay_path)
            print("overlay:", overlay_path)
    else:
        warnings.append("no image available for overlay/card-presence checks")

    print("game_dir:", game_dir)
    print("coordinates:", coord_path)
    print("origin:", table_capture_origin(table_capture))
    print("templates:", len(templates))
    print("regions:", len(regions))

    if warnings:
        print("warnings:")
        for warning in warnings:
            print("  -", warning)
    if errors:
        print("errors:")
        for error in errors:
            print("  -", error)
        return 1

    print("status: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
