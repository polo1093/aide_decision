#!/usr/bin/env python3
"""Extract action/state templates from a profile video."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from profile_common import (
    POKERTH_ACTION_BOXES,
    first_video,
    game_dir_for,
    load_payload,
    parse_template_spec,
    read_video_frame,
)


def _load_specs(args: argparse.Namespace) -> dict[str, tuple[int, tuple[int, int, int, int]]]:
    specs: dict[str, tuple[int, tuple[int, int, int, int]]] = {}
    if args.preset == "pokerth":
        specs.update(POKERTH_ACTION_BOXES)

    if args.spec_file:
        data = load_payload(Path(args.spec_file))
        raw = data.get("templates", data)
        if not isinstance(raw, dict):
            raise ValueError("Spec file must be an object or contain a 'templates' object")
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid spec entry for {name}")
            frame = int(entry["frame"])
            box = entry["box"]
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError(f"Invalid box for {name}")
            specs[str(name)] = (frame, tuple(int(v) for v in box))  # type: ignore[arg-type]

    for raw_spec in args.template or []:
        name, frame, box = parse_template_spec(raw_spec)
        specs[name] = (frame, box)

    return specs


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract check/raise/call/fold/etc. templates from video frame boxes."
    )
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--video", help="Video path; defaults to first video found in profile directory")
    parser.add_argument("--preset", choices=("none", "pokerth"), default="none")
    parser.add_argument("--spec-file", help="JSON spec with {templates:{name:{frame,box}}}")
    parser.add_argument(
        "--template",
        action="append",
        help="Template spec name.png:frame:x1,y1,x2,y2. Box is relative to the table crop.",
    )
    parser.add_argument("--out-dir", help="Defaults to profile directory")
    args = parser.parse_args(argv)

    game_dir = game_dir_for(args.game, args.game_dir)
    video_path = Path(args.video) if args.video else first_video(game_dir)
    if video_path is None:
        raise SystemExit(f"ERROR: no video found in {game_dir}")

    specs = _load_specs(args)
    if not specs:
        raise SystemExit("ERROR: no templates requested. Use --preset, --spec-file, or --template.")

    out_dir = Path(args.out_dir) if args.out_dir else game_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, (frame_index, box) in specs.items():
        image = read_video_frame(video_path, frame_index)
        coord_path = game_dir / "coordinates.json"
        origin = [0, 0]
        if coord_path.exists():
            payload = load_payload(coord_path)
            table_capture = payload.get("table_capture", {})
            if isinstance(table_capture, dict):
                raw_origin = table_capture.get("origin") or (table_capture.get("bounds") or [0, 0])[:2]
                if isinstance(raw_origin, list) and len(raw_origin) >= 2:
                    origin = [int(raw_origin[0]), int(raw_origin[1])]

        x1, y1, x2, y2 = box
        crop_box = (origin[0] + x1, origin[1] + y1, origin[0] + x2, origin[1] + y2)
        out_path = out_dir / name
        image.crop(crop_box).save(out_path)
        print(f"{out_path} frame={frame_index} box={box}")

    spec_out = out_dir / "action_templates.spec.json"
    with spec_out.open("w", encoding="utf-8") as fh:
        json.dump(
            {"templates": {name: {"frame": frame, "box": list(box)} for name, (frame, box) in specs.items()}},
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")
    print("spec:", spec_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
