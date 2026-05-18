#!/usr/bin/env python3
"""identify_card.py — labellisation incrémentale des cartes.

Parcourt les captures plein écran dans ``config/<jeu>/entrainement/screens``, extrait les
patches *number* et *suit* selon `coordinates.json`, tente une reco par gabarits
en mettant à jour le dataset **au fil de l'eau** :

- pour chaque carte :
    * si valeur+couleur sont connues avec un score >= strict → autoskip, aucune UI;
    * sinon, ouverture d’un mini-dialog qui ne demande que la partie inconnue;
    * les patches labellisés sont immédiatement ajoutés à `cards/` et à l’index;
      les cartes suivantes bénéficient donc des nouvelles infos.

Usage minimal:
    python scripts/identify_card.py --game PMU

Options utiles:
  --screens-dir   Dossier d’entrée (défaut: config/<jeu>/entrainement/screens)
  --strict        Score min (0-1) pour autoskip complet (def 0.985)
  --trim          Bordure rognée (px) pour reco & sauvegarde (def 6)
  --force-all     Forcer le dialog même si la reco est déjà suffisante
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, Sequence, Tuple, Optional

# Compat OpenCV pour PyScreeze
try:
    import cv2
except ImportError:
    cv2 = None
else:
    for missing_attr, fallback_attr in (
        ("CV_LOAD_IMAGE_COLOR", "IMREAD_COLOR"),
        ("CV_LOAD_IMAGE_GRAYSCALE", "IMREAD_GRAYSCALE"),
    ):
        if not hasattr(cv2, missing_attr) and hasattr(cv2, fallback_attr):
            setattr(cv2, missing_attr, getattr(cv2, fallback_attr))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image

from objet.services.card_identifier import CardIdentifier, is_card_present
from objet.scanner.cards_recognition import is_cover_me_cards
from _utils import (
    CardPatch,
    collect_card_patches,
    coerce_int,
    load_coordinates,
    table_capture_origin,
)

DEFAULT_ACCEPT_THRESHOLD = 0.95


# ---------- helpers fichiers / ancre ----------

def _iter_capture_files(directory: Path) -> Iterable[Path]:
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
        yield from sorted(directory.glob(ext))


def _find_anchor(game_dir: Path) -> Optional[Path]:
    for ext in (".png", ".jpg", ".jpeg"):
        candidate = game_dir / f"anchor{ext}"
        if candidate.exists():
            return candidate
    return None


def _expected_anchor_from_capture(
    table_capture: Dict[str, object],
    ref_img: Optional[Image.Image],
) -> Optional[Tuple[int, int]]:
    if not ref_img:
        return None
    if not isinstance(table_capture, dict):
        return None
    origin = table_capture_origin(table_capture)
    offset_raw = table_capture.get("ref_offset")
    if isinstance(offset_raw, (list, tuple)):
        values = list(offset_raw)
    else:
        values = []
    if len(values) >= 2:
        ox = origin[0] + coerce_int(values[0])
        oy = origin[1] + coerce_int(values[1])
        return ox, oy
    if origin != (0, 0):
        return origin
    return None


def _match_anchor(frame: Image.Image, anchor: Image.Image) -> Tuple[Tuple[int, int], float]:
    frame_gray = cv2.cvtColor(np.array(frame.convert("RGB")), cv2.COLOR_RGB2GRAY)
    anchor_gray = cv2.cvtColor(np.array(anchor.convert("RGB")), cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(frame_gray, anchor_gray, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(result)
    return (int(loc[0]), int(loc[1])), float(score)


def _compute_anchor_offset(
    frame: Image.Image,
    anchor: Optional[Image.Image],
    expected: Optional[Tuple[int, int]],
    *,
    threshold: float = 0.75,
) -> Tuple[Tuple[int, int], Optional[float]]:
    if anchor is None or expected is None:
        return (0, 0), None
    (ax, ay), score = _match_anchor(frame, anchor)
    if score < threshold:
        return (0, 0), score
    dx = ax - expected[0]
    dy = ay - expected[1]
    return (dx, dy), score


def _load_table_image(img_path: Path) -> Optional[Image.Image]:
    try:
        with Image.open(img_path) as im:
            return im.convert("RGB")
    except FileNotFoundError:
        return None


# ---------- helpers cartes / overlay ----------

_HAND_HINTS = ("hand", "player", "hero", "me")
_BOARD_HINTS = ("board", "community", "table")


def _card_patch_present(card_patch: CardPatch) -> bool:
    """Détection 'slot non vide' via la présence d'une carte."""
    return is_card_present(card_patch.number, threshold=215, min_ratio=0.04)


def _infer_template_set_from_key(base_key: str) -> Optional[str]:
    key = base_key.lower()
    if any(hint in key for hint in _HAND_HINTS):
        return "hand"
    if any(hint in key for hint in _BOARD_HINTS):
        return "board"
    return None


def _normalise_template_set(card_patch: CardPatch, base_key: str) -> Optional[str]:
    if card_patch.template_set:
        return card_patch.template_set
    return _infer_template_set_from_key(base_key)


def _is_hand_slot(template_set: Optional[str]) -> bool:
    if not template_set:
        return False
    lower = template_set.lower()
    if any(hint in lower for hint in _BOARD_HINTS):
        return False
    return any(hint in lower for hint in _HAND_HINTS) or not lower


def _crop_region(table_img: Image.Image, region, offset: Tuple[int, int] = (0, 0)) -> Image.Image:
    """Retourne un crop PIL à partir d'une région de coordinates.json et d'un offset."""
    x, y = region.top_left
    w, h = region.size
    ox, oy = offset
    return table_img.crop((x + ox, y + oy, x + ox + w, y + oy + h))


# ---------- CLI ----------

def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Labellisation incrémentale des cartes")
    parser.add_argument("--game", default="PMU", help="Identifiant du jeu (dossier dans config/)")
    parser.add_argument(
        "--screens-dir",
        "--crops-dir",
        dest="screens_dir",
        help="Dossier contenant les captures plein écran à analyser",
    )
    parser.add_argument("--strict", type=float, default=0.985, help="Score min (0-1) pour autoskip complet")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_ACCEPT_THRESHOLD,
        help="Score min (0-1) pour accepter une valeur/couleur",
    )
    parser.add_argument("--trim", type=int, default=6, help="Bordure rognée pour reco & sauvegarde (px)")
    parser.add_argument("--force-all", action="store_true", help="Toujours ouvrir l’UI même si autoskip possible")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    game_dir = Path("config") / args.game
    coords_path = game_dir / "coordinates.json"
    if not coords_path.exists():
        print(f"ERREUR: fichier de coordonnées introuvable ({coords_path})")
        return 2

    screens_dir = Path(args.screens_dir) if args.screens_dir else game_dir / "entrainement" / "screens"
    if not screens_dir.exists():
        print(f"ERREUR: dossier de captures introuvable ({screens_dir})")
        return 2

    regions, _, table_capture = load_coordinates(coords_path)

    # Service incrémental
    identifier = CardIdentifier(
        game_dir,
        trim=int(args.trim),
        threshold=float(args.threshold),
        strict=float(args.strict),
    )

    anchor_path = _find_anchor(game_dir)
    anchor_img = Image.open(anchor_path).convert("RGBA") if anchor_path else None
    anchor_expected = _expected_anchor_from_capture(table_capture, anchor_img)

    capture_paths = list(_iter_capture_files(screens_dir))
    if not capture_paths:
        print(f"Aucune capture trouvée dans {screens_dir}")
        return 0

    total_cards = 0
    auto_ok = 0
    labeled = 0
    skipped_empty = 0
    skipped_hold = 0

    for img_path in capture_paths:
        table_img = _load_table_image(img_path)
        if table_img is None:
            continue

        offset, score = _compute_anchor_offset(
            table_img,
            anchor_img,
            anchor_expected,
            threshold=0.75,
        )
        if score is not None and score < 0.75:
            print(f"[WARN] Anchor score {score:.3f} trop faible pour {img_path.name}; offset ignoré")
            offset = (0, 0)

        # Détection overlay joueur sur la bbox player_state_me
        state_region = regions.get("player_state_me")
        if state_region is not None:
            state_patch = _crop_region(table_img, state_region, offset)
            has_cover_me = is_cover_me_cards(state_patch, threshold=0.55)
        else:
            has_cover_me = False

        card_pairs = collect_card_patches(
            table_img,
            regions,
            pad=0,
            table_capture=table_capture,
            offset=offset,
        )

        overlay_skipped = 0
        for base_key, card_patch in card_pairs.items():
            tpl_set = _normalise_template_set(card_patch, base_key)

            if not _card_patch_present(card_patch):
                skipped_empty += 1
                continue

            if has_cover_me and _is_hand_slot(tpl_set):
                skipped_hold += 1
                overlay_skipped += 1
                continue

            total_cards += 1

            res = identifier.identify_from_patches(
                card_patch.number,
                card_patch.suit,
                base_key=base_key,
                template_set=tpl_set,
                interactive=True,
                force_all=bool(args.force_all),
            )

            src = (res.meta.get("source") or "").lower()

            if src == "auto":
                auto_ok += 1
                print(
                    f"[AUTO] {img_path.name} {base_key} → {res.number} / {res.suit} "
                    f"(scores: {res.meta.get('score_number'):.3f}, {res.meta.get('score_suit'):.3f})"
                )
            elif src == "labeled":
                labeled += 1
                print(f"[LAB]  {img_path.name} {base_key} → {res.number} / {res.suit}")
            elif src == "cancel":
                print(f"[CANCEL] {img_path.name} {base_key} → meilleure hypothèse {res.number}/{res.suit}")
            elif src == "guess":
                print(f"[GUESS] {img_path.name} {base_key} → {res.number}/{res.suit}")
            elif src == "delete":
                # suppression physique de la capture problématique
                try:
                    img_path.unlink()
                    print(f"[DELETE] {img_path.name} supprimée")
                except OSError as e:
                    print(f"[DELETE-ERR] {img_path.name}: {e}")
                # on arrête le traitement des autres cartes de cette capture
                break
            else:
                # debug si un nouveau source apparaît
                print(f"[DEBUG] {img_path.name} {base_key}: source inattendue {src!r}")

        if overlay_skipped:
            print(
                f"[SKIP] {img_path.name}: overlay joueur détecté, {overlay_skipped} carte(s) main ignorées"
            )

    print("==== RÉSUMÉ ====")
    print(f"Cartes vues              : {total_cards}")
    print(f"  dont autoskip (strict) : {auto_ok}")
    print(f"  dont labellées (UI)    : {labeled}")
    print(f"Cartes vides             : {skipped_empty}")
    print(f"Cartes skip HOLD/FOLD    : {skipped_hold}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
