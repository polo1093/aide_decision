from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

import cv2
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.calibration import Region, load_coordinates, table_capture_origin
from scripts.crop_core import infer_size_and_offset


IMAGE_EXTS = (".png", ".jpg", ".jpeg")
VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".mov")
ACTION_TEMPLATE_NAMES = (
    "check.png",
    "paie.png",
    "relance.png",
    "fold.png",
    "play.png",
    "sit_out.png",
)


DEFAULT_TEMPLATES: dict[str, dict[str, Any]] = {
    "action_button": {
        "size": [162, 40],
        "type": "texte",
        "layout": {"lock_same_x": True},
    },
    "player_money": {"size": [86, 18], "type": "nombre"},
    "player_name": {"size": [95, 18], "type": "texte"},
    "other_money": {"size": [115, 40], "type": "nombre"},
    "board_card_number": {
        "size": [30, 38],
        "type": "carte_numero",
        "layout": {"lock_same_y": True},
    },
    "board_card_symbol": {
        "size": [30, 34],
        "type": "carte_symbole",
        "layout": {"lock_same_y": True},
    },
    "player_card_number": {
        "size": [30, 38],
        "type": "carte_numero",
        "layout": {"lock_same_y": True},
    },
    "player_card_symbol": {
        "size": [30, 34],
        "type": "carte_symbole",
        "layout": {"lock_same_y": True},
    },
    "player_state": {"size": [160, 110], "type": "etat"},
}


POKERTH_ACTION_BOXES: dict[str, tuple[int, tuple[int, int, int, int]]] = {
    "check.png": (160, (98, 149, 158, 166)),
    "paie.png": (0, (103, 152, 150, 168)),
    "relance.png": (480, (307, 114, 362, 131)),
    "fold.png": (480, (102, 306, 143, 322)),
    "play.png": (720, (90, 93, 158, 168)),
    "sit_out.png": (0, (900, 275, 980, 330)),
}


def game_dir_for(game: str, game_dir: Optional[str] = None) -> Path:
    return Path(game_dir) if game_dir else PROJECT_ROOT / "config" / game


def first_existing(game_dir: Path, stems: Sequence[str], exts: Sequence[str]) -> Optional[Path]:
    for stem in stems:
        for ext in exts:
            path = game_dir / f"{stem}{ext}"
            if path.exists():
                return path
    return None


def first_video(game_dir: Path) -> Optional[Path]:
    for path in sorted(game_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
            return path
    for path in sorted((game_dir / "entrainement").glob("**/*")) if (game_dir / "entrainement").exists() else []:
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
            return path
    return None


def load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON payload: {path}")
    return data


def save_payload(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def infer_table_capture(game_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    screenshot_path = first_existing(game_dir, ("test_crop", "test_screen", "test_fullscreen"), IMAGE_EXTS)
    expected_path = first_existing(game_dir, ("test_crop_result", "test_table"), IMAGE_EXTS)
    anchor_path = first_existing(game_dir, ("anchor",), IMAGE_EXTS)
    if screenshot_path is None:
        raise FileNotFoundError(f"Missing full-screen capture in {game_dir}")
    if expected_path is None:
        raise FileNotFoundError(f"Missing table crop capture in {game_dir}")
    if anchor_path is None:
        raise FileNotFoundError(f"Missing anchor image in {game_dir}")

    screenshot = Image.open(screenshot_path).convert("RGBA")
    expected = Image.open(expected_path).convert("RGBA")
    anchor = Image.open(anchor_path).convert("RGBA")
    size, ref_offset, crop_pos, ref_pos = infer_size_and_offset(screenshot, expected, anchor)
    x, y = crop_pos
    w, h = size
    return (
        {
            "enabled": True,
            "bounds": [int(x), int(y), int(x + w), int(y + h)],
            "origin": [int(x), int(y)],
            "size": [int(w), int(h)],
            "ref_offset": [int(ref_offset[0]), int(ref_offset[1])],
        },
        {
            "screenshot": str(screenshot_path),
            "expected": str(expected_path),
            "anchor": str(anchor_path),
            "crop_pos": [int(crop_pos[0]), int(crop_pos[1])],
            "ref_pos": [int(ref_pos[0]), int(ref_pos[1])],
        },
    )


def region(group: str, origin: tuple[int, int], rel: tuple[int, int], *, label: str, template_set: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "group": group,
        "top_left": [int(origin[0] + rel[0]), int(origin[1] + rel[1])],
        "value": None,
        "label": label,
    }
    if template_set:
        payload["template_set"] = template_set
    return payload


def pokerth_regions(origin: Sequence[int]) -> dict[str, dict[str, Any]]:
    ox, oy = int(origin[0]), int(origin[1])
    org = (ox, oy)
    out: dict[str, dict[str, Any]] = {}

    for idx, rel_y in enumerate((478, 521, 562), start=1):
        out[f"button_{idx}"] = region("action_button", org, (432, rel_y), label=f"button_{idx}")

    for name, rel in {
        "fond": (484, 365),
        "player_money_J1": (280, 370),
        "player_money_J2": (70, 331),
        "player_money_J3": (70, 83),
        "player_money_J4": (280, 52),
        "player_money_J5": (875, 331),
    }.items():
        out[name] = region("player_money", org, rel, label=name)

    for name, rel in {
        "player_name_J1": (280, 384),
        "player_name_J2": (70, 345),
        "player_name_J3": (70, 69),
        "player_name_J4": (280, 38),
        "player_name_J5": (875, 345),
    }.items():
        out[name] = region("player_name", org, rel, label=name)

    for name, rel in {
        "player_state_me": (430, 285),
        "player_state_J1": (220, 285),
        "player_state_J2": (15, 245),
        "player_state_J3": (15, 65),
        "player_state_J4": (220, 35),
        "player_state_J5": (850, 245),
    }.items():
        out[name] = region("player_state", org, rel, label=name)

    for idx, x in enumerate((503, 538), start=1):
        out[f"player_card_{idx}_number"] = region(
            "player_card_number", org, (x, 287), label=f"player_card_{idx}_number", template_set="hand"
        )
        out[f"player_card_{idx}_symbol"] = region(
            "player_card_symbol", org, (x + 4, 329), label=f"player_card_{idx}_symbol", template_set="hand"
        )

    for idx, x in enumerate((394, 448, 504, 558, 614), start=1):
        out[f"board_card_{idx}_number"] = region(
            "board_card_number", org, (x, 175), label=f"board_card_{idx}_number", template_set="board"
        )
        out[f"board_card_{idx}_symbol"] = region(
            "board_card_symbol", org, (x + 4, 217), label=f"board_card_{idx}_symbol", template_set="board"
        )

    out["pot"] = region("other_money", org, (246, 202), label="pot")
    return out


def read_video_frame(video_path: Path, frame_index: int) -> Image.Image:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Cannot read frame {frame_index} from {video_path}")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGB")
    finally:
        cap.release()


def video_metadata(video_path: Path) -> dict[str, float]:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        return {
            "width": float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0),
            "height": float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0),
            "fps": fps,
            "frames": frames,
            "duration": frames / fps if fps else 0.0,
        }
    finally:
        cap.release()


def crop_to_capture(image: Image.Image, table_capture: Mapping[str, Any]) -> Image.Image:
    bounds = table_capture.get("bounds")
    if isinstance(bounds, Sequence) and len(bounds) == 4:
        x1, y1, x2, y2 = [int(v) for v in bounds]
        if image.width >= x2 and image.height >= y2:
            return image.crop((x1, y1, x2, y2))

    size = table_capture.get("size")
    if isinstance(size, Sequence) and len(size) == 2 and image.size == (int(size[0]), int(size[1])):
        return image.copy()

    return image.copy()


def region_relative_box(region_obj: Region, origin: tuple[int, int]) -> tuple[int, int, int, int]:
    x = int(region_obj.top_left[0] - origin[0])
    y = int(region_obj.top_left[1] - origin[1])
    w, h = region_obj.size
    return x, y, x + int(w), y + int(h)


def draw_regions(
    image: Image.Image,
    regions: Mapping[str, Region],
    table_capture: Mapping[str, Any],
    *,
    labels: bool = True,
) -> Image.Image:
    out = image.convert("RGB").copy()
    origin = table_capture_origin(table_capture)
    colors = ("red", "yellow", "cyan", "magenta", "lime", "orange", "white")
    draw = ImageDraw.Draw(out)
    for index, (name, reg) in enumerate(regions.items()):
        box = region_relative_box(reg, origin)
        color = colors[index % len(colors)]
        draw.rectangle(box, outline=color, width=2)
        if labels:
            x1, y1, _x2, _y2 = box
            draw.text((x1, max(0, y1 - 10)), name, fill=color)
    return out


def parse_box(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("Box must be x1,y1,x2,y2")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def parse_template_spec(value: str) -> tuple[str, int, tuple[int, int, int, int]]:
    try:
        name, frame_raw, box_raw = value.split(":", 2)
    except ValueError as exc:
        raise ValueError("Template spec must be name.png:frame:x1,y1,x2,y2") from exc
    return name, int(frame_raw), parse_box(box_raw)
