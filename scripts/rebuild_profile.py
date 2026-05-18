#!/usr/bin/env python3
"""Rebuild the capture geometry and optional region preset for a game profile."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from profile_common import (
    DEFAULT_TEMPLATES,
    game_dir_for,
    infer_table_capture,
    load_payload,
    pokerth_regions,
    save_payload,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Infer table_capture from test images and optionally seed profile regions."
    )
    parser.add_argument("--game", default="PMU", help="Folder name under config/")
    parser.add_argument("--game-dir", help="Explicit profile directory")
    parser.add_argument(
        "--preset",
        choices=("none", "pokerth"),
        default="none",
        help="Optional region preset to write when coordinates are missing or --force-preset is used.",
    )
    parser.add_argument(
        "--force-preset",
        action="store_true",
        help="Overwrite existing templates/regions with the selected preset.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Only print inferred geometry; do not write coordinates.json.",
    )
    args = parser.parse_args(argv)

    game_dir = game_dir_for(args.game, args.game_dir)
    coord_path = game_dir / "coordinates.json"
    payload = load_payload(coord_path)
    table_capture, source_info = infer_table_capture(game_dir)

    payload["table_capture"] = table_capture
    if "templates" not in payload or args.force_preset or args.preset != "none":
        payload.setdefault("templates", DEFAULT_TEMPLATES)

    if args.preset == "pokerth":
        if args.force_preset or not payload.get("regions"):
            payload["templates"] = DEFAULT_TEMPLATES
            payload["regions"] = pokerth_regions(table_capture["origin"])
    else:
        payload.setdefault("templates", DEFAULT_TEMPLATES)
        payload.setdefault("regions", {})

    print("game_dir:", game_dir)
    print("coordinates:", coord_path)
    print("table_capture:", table_capture)
    print("source:", source_info)
    print("regions:", len(payload.get("regions", {})))

    if not args.no_write:
        save_payload(coord_path, payload)
        print("wrote:", coord_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
