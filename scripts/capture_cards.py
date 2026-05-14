#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cartes — extraction, matching, contrôleur de table et outils vidéo/labeling.

Regroupe les anciennes fonctionnalités de:
- cards_core.py
- cards_validate.py
- controller.py
- capture_source.py
- labeler_cli.py
- run_video_validate.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image

# Accès modules du dépôt (pour exécution directe depuis scripts/)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
for root in (PROJECT_ROOT, SCRIPTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from _utils import (
    CardPatch,
    collect_card_patches,
    coerce_int,
    load_coordinates,
    table_capture_origin,
)
from objet.scanner.cards_recognition import (
    CardObservation,
    TemplateIndex,
    is_card_present,
    recognize_number_and_suit,
)

if TYPE_CHECKING:  # hints uniquement
    from objet.services.game import Game


# ==============================
# Modèle / observations de cartes
# ==============================

# Les classes et fonctions de reconnaissance sont fournies par
# ``objet.scanner.cards_recognition`` pour éviter les imports circulaires.



# ==============================
# cards_validate — CLI de vérification basique sur une image
# ==============================


def _find_first(game_dir: Path, base: str, exts=(".png", ".jpg", ".jpeg")) -> Optional[Path]:
    for ext in exts:
        p = game_dir / f"{base}{ext}"
        if p.exists():
            return p
    return None


def _auto_paths_for_game(game: str, game_dir_opt: Optional[str]) -> dict:
    game_dir = Path(game_dir_opt) if game_dir_opt else Path("config") / (game or "PMU")
    table = None
    for stem in ("test_screen", "test_fullscreen", "test_table", "test_crop_result"):
        table = _find_first(game_dir, stem)
        if table:
            break
    coords = game_dir / "coordinates.json"
    cards_root = game_dir / "cards"
    return {"game_dir": game_dir, "table": table, "coords": coords, "cards_root": cards_root}


def _save_png(p: Path, img: Image.Image) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.save(p)


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
    if isinstance(offset_raw, Iterable):
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
    threshold: float = 0.8,
) -> Tuple[Tuple[int, int], Optional[float]]:
    if anchor is None or expected is None:
        return (0, 0), None
    (ax, ay), score = _match_anchor(frame, anchor)
    if score < threshold:
        return (0, 0), score
    dx = ax - expected[0]
    dy = ay - expected[1]
    return (dx, dy), score


def main_cards_validate(argv: Optional[list] = None) -> int:
    """Vérifie l'extraction + matching des cartes pour un jeu donné.

    Utilise une capture plein écran (ex: test_screen.* dans config/<game>/).
    """

    parser = argparse.ArgumentParser(description="Vérifie l'extraction + matching des cartes pour un jeu")
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--dump", action="store_true", help="Sauver extraits dans entrainement/cards/")
    parser.add_argument("--num-th", type=float, default=0.6, help="Seuil score pour numbers (0..1)")
    parser.add_argument("--suit-th", type=float, default=0.6, help="Seuil score pour suits (0..1)")
    parser.add_argument("--pad", type=int, default=4)
    args = parser.parse_args(argv)

    auto = _auto_paths_for_game(args.game, args.game_dir)
    table_path: Optional[Path] = auto["table"]
    coords_path: Path = auto["coords"]
    cards_root: Path = auto["cards_root"]

    if not table_path or not table_path.exists():
        raise SystemExit("ERROR: aucune capture plein écran trouvée (utilisez --table ou placez test_screen.* dans le dossier du jeu)")
    if not coords_path.exists():
        raise SystemExit("ERROR: coordinates.json not found")
    if not cards_root.exists():
        raise SystemExit("ERROR: cards folder not found (expected numbers/ and suits/)")

    # 1) Charger index
    idx = TemplateIndex(cards_root)
    idx.load()
    expect_numbers = ["A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2"]
    expect_suits = ["hearts", "diamonds", "clubs", "spades"]
    missing = idx.check_missing(expect_numbers=expect_numbers, expect_suits=expect_suits)
    if missing["numbers"] or missing["suits"]:
        print("Missing templates:")
        if missing["numbers"]:
            print("  numbers:", ", ".join(missing["numbers"]))
        if missing["suits"]:
            print("  suits:", ", ".join(missing["suits"]))
        missing_cards = idx.missing_cards(expect_numbers, expect_suits)
        if missing_cards:
            print("  card combinations:")
            for combo in missing_cards:
                print(f"    - {combo}")
        return 2

    # 2) Charger table et coordonnées
    table_img = Image.open(table_path).convert("RGBA")

    # Import local pour limiter les risques d'import circulaire
    from objet.services.game import Game  # type: ignore[import]

    game = Game.for_script(Path(__file__).name)
    regions, resolved, table_capture = load_coordinates(coords_path)
    game.update_from_capture(
        table_capture=table_capture,
        regions={k: {"group": r.group, "top_left": r.top_left, "size": r.size} for k, r in regions.items()},
        templates=resolved,
        reference_path=str(table_path) if table_path else None,
    )

    anchor_path = _find_first(auto["game_dir"], "anchor")
    anchor_img = Image.open(anchor_path).convert("RGBA") if anchor_path else None
    anchor_expected = _expected_anchor_from_capture(table_capture, anchor_img)
    offset, score = _compute_anchor_offset(
        table_img,
        anchor_img,
        anchor_expected,
        threshold=0.75,
    )
    if score is not None:
        print(f"Anchor match score: {score:.3f} (offset={offset})")

    # 3) Extraire patches cartes
    pairs = collect_card_patches(
        table_img,
        regions,
        pad=int(args.pad),
        table_capture=table_capture,
        offset=offset,
    )
    if not pairs:
        print("No card regions found (check coordinates.json groups)")
        return 2

    # 4) Reconnaissance
    ok = True
    training_dir = auto["game_dir"] / "entrainement" / "cards"
    for base_key, card_patch in pairs.items():
        patch_num = card_patch.number
        patch_suit = card_patch.suit
        # filtre présence
        if not is_card_present(patch_num):  # si la zone nombre semble vide, on ignore la carte
            print(f"{base_key}: probably empty (skip)")
            continue
        val, suit, s_val, s_suit = recognize_number_and_suit(
            patch_num,
            patch_suit,
            idx,
            template_set=card_patch.template_set,
        )

        obs = CardObservation(value=val, suit=suit, value_score=s_val, suit_score=s_suit, source="capture")
        if hasattr(game, "add_card_observation"):
            game.add_card_observation(base_key, obs)

        hit_val = val is not None and s_val >= float(args.num_th)
        hit_suit = suit is not None and s_suit >= float(args.suit_th)
        status = "OK" if (hit_val and hit_suit) else "LOW"
        print(f"{base_key}: {status}  value={val} ({s_val:.3f})  suit={suit} ({s_suit:.3f})")
        if args.dump:
            _save_png(training_dir / f"{base_key}_number.png", patch_num)
            _save_png(training_dir / f"{base_key}_symbol.png", patch_suit)
        if not (hit_val and hit_suit):
            ok = False

    # Résumé éventuel si Game expose des cartes formatées
    if hasattr(game, "cards") and hasattr(game.cards, "as_strings"):
        summary = game.cards.as_strings()
        player = summary.get("player") or []
        board = summary.get("board") or []
        print("Résumé Game → joueur:", ", ".join(player))
        print("Résumé Game → board:", ", ".join(board))

    return 0 if ok else 1


# ==============================
# État de table / contrôleur runtime
# ==============================


@dataclass
class CardState:
    value: Optional[str] = None
    suit: Optional[str] = None
    value_score: float = 0.0
    suit_score: float = 0.0
    stable: int = 0  # nb frames consécutifs où l'observation est identique et au-dessus des seuils
    last_seen: int = -1


class TableState:
    def __init__(self) -> None:
        self.cards: Dict[str, CardState] = {}  # base_key -> state

    def update(
        self,
        base_key: str,
        obs: CardObservation,
        frame_idx: int,
        *,
        num_th: float,
        suit_th: float,
        require_k: int = 2,
    ) -> bool:
        """Met à jour l'état d'une carte.

        Retourne True si une nouvelle valeur stabilisée (changement) est atteinte.
        """

        confident = (
            obs.value is not None
            and obs.value_score >= num_th
            and obs.suit is not None
            and obs.suit_score >= suit_th
        )

        st = self.cards.get(base_key, CardState())

        if confident:
            same = (st.value == obs.value) and (st.suit == obs.suit)
            st.stable = (st.stable + 1) if same else 1
            st.value, st.suit = obs.value, obs.suit
            st.value_score, st.suit_score = obs.value_score, obs.suit_score
            st.last_seen = frame_idx
            changed = (st.stable == require_k) and (not same)  # première fois où on atteint K
        else:
            st.stable = 0
            st.last_seen = frame_idx
            changed = False

        self.cards[base_key] = st
        return changed

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        return {
            k: {
                "value": v.value,
                "suit": v.suit,
                "value_score": v.value_score,
                "suit_score": v.suit_score,
                "stable": v.stable,
            }
            for k, v in self.cards.items()
        }


class TableController:
    """Orchestrateur runtime (capture → extraction → matching → état)."""

    def __init__(self, game_dir: Path, game_state: Optional["Game"] = None) -> None:
        # Import local pour éviter les imports circulaires si objet.services.game
        # importe à son tour des scripts.
        from objet.services.game import Game  # type: ignore[import]

        self.game_dir = Path(game_dir)
        self.coords_path = self.game_dir / "coordinates.json"
        self.ref_path = self._first_of("anchor", (".png", ".jpg", ".jpeg"))

        self.game: Game = game_state or Game.for_script(Path(__file__).name)

        self.regions, self.templates, table_capture = load_coordinates(self.coords_path)
        self.table_capture = dict(table_capture)
        self.game.update_from_capture(
            table_capture=table_capture,
            regions={k: {"group": r.group, "top_left": r.top_left, "size": r.size} for k, r in self.regions.items()},
            templates=self.templates,
            reference_path=str(self.ref_path) if self.ref_path else None,
        )

        self.ref_img: Optional[Image.Image] = (
            Image.open(self.ref_path).convert("RGBA") if self.ref_path else None
        )
        self.anchor_expected = _expected_anchor_from_capture(self.table_capture, self.ref_img)
        self.anchor_threshold = 0.8
        self.last_offset: Tuple[int, int] = (0, 0)

        self.idx = TemplateIndex(self.game_dir / "cards")
        self.idx.load()
        self.state = TableState()

    def _first_of(self, stem: str, exts: Iterable[str]) -> Optional[Path]:
        for ext in exts:
            p = self.game_dir / f"{stem}{ext}"
            if p.exists():
                return p
        return None

    def process_frame(
        self,
        frame_rgba: Image.Image,
        frame_idx: int,
        *,
        num_th: float = 0.6,
        suit_th: float = 0.6,
        require_k: int = 2,
    ) -> Dict[str, Dict[str, object]]:
        """Traite un frame et retourne un snapshot d'état de table."""

        offset, score = _compute_anchor_offset(
            frame_rgba,
            self.ref_img,
            self.anchor_expected,
            threshold=self.anchor_threshold,
        )
        self.last_offset = offset
        if score is not None and score < self.anchor_threshold:
            print(
                f"[WARN] Référence carte: score {score:.3f} < {self.anchor_threshold:.2f}; utilisation des coordonnées nominales"
            )

        pairs = collect_card_patches(
            frame_rgba,
            self.regions,
            pad=4,
            table_capture=self.table_capture,
            offset=offset,
        )

        # 3) matching + mise à jour d'état
        for base_key, card_patch in pairs.items():
            patch_num = card_patch.number
            patch_suit = card_patch.suit
            if not is_card_present(patch_num):
                continue
            val, suit, s_val, s_suit = recognize_number_and_suit(
                patch_num,
                patch_suit,
                self.idx,
                template_set=card_patch.template_set,
            )
            obs = CardObservation(val, suit, s_val, s_suit, source="capture")
            self.state.update(
                base_key,
                obs,
                frame_idx,
                num_th=float(num_th),
                suit_th=float(suit_th),
                require_k=int(require_k),
            )
            if hasattr(self.game, "add_card_observation"):
                self.game.add_card_observation(base_key, obs)

        return self.state.snapshot()


# ==============================
# capture_source — vidéo → frames PIL
# ==============================


class VideoFrameSource:
    def __init__(self, path: str, *, bgr_to_rgb: bool = True) -> None:
        self.cap = cv2.VideoCapture(path)
        self.bgr_to_rgb = bgr_to_rgb
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")

    def __iter__(self) -> Iterator[Image.Image]:
        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            if self.bgr_to_rgb:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            yield Image.fromarray(frame).convert("RGBA")
        self.cap.release()


# ==============================
# labeler_cli — collecte des inconnus & labellisation simple
# ==============================


class SampleSink:
    """Sauvegarde les extraits non reconnus vers config/<game>/unlabeled/…"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _unlabeled_root(self, template_set: Optional[str]) -> Path:
        base = self.root / "unlabeled"
        if template_set:
            return base / template_set
        return base

    def save_number(
        self,
        key: str,
        img: Image.Image,
        frame_idx: int,
        template_set: Optional[str] = None,
    ) -> Path:
        root = self._unlabeled_root(template_set)
        p = root / "numbers" / f"{key}_{frame_idx}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p)
        return p

    def save_suit(
        self,
        key: str,
        img: Image.Image,
        frame_idx: int,
        template_set: Optional[str] = None,
    ) -> Path:
        root = self._unlabeled_root(template_set)
        p = root / "suits" / f"{key}_{frame_idx}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(p)
        return p


class InteractiveLabeler:
    def __init__(self, cards_root: Path) -> None:
        self.cards_root = Path(cards_root)

    def add_number(
        self,
        img_path: Path,
        label: str,
        template_set: Optional[str] = None,
    ) -> Path:
        root = self.cards_root / template_set if template_set else self.cards_root
        dst = root / "numbers" / label / img_path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        Image.open(img_path).save(dst)
        return dst

    def add_suit(
        self,
        img_path: Path,
        label: str,
        template_set: Optional[str] = None,
    ) -> Path:
        root = self.cards_root / template_set if template_set else self.cards_root
        dst = root / "suits" / label / img_path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        Image.open(img_path).save(dst)
        return dst


# ==============================
# run_video_validate — CLI vidéo → détection en ligne + stockage inconnus
# ==============================


def main_video_validate(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valide détection cartes sur une vidéo (extraction+match+mémoire)"
    )
    parser.add_argument("--game", default="PMU")
    parser.add_argument("--game-dir")
    parser.add_argument("--video", required=True)
    parser.add_argument("--stride", type=int, default=3, help="Ne traiter qu'un frame sur N (perf)")
    parser.add_argument("--num-th", type=float, default=0.65)
    parser.add_argument("--suit-th", type=float, default=0.65)
    parser.add_argument("--require-k", type=int, default=2, help="Nb de frames pour stabiliser")
    args = parser.parse_args(argv)

    game_dir = Path(args.game_dir) if args.game_dir else Path("config") / (args.game or "PMU")
    ctrl = TableController(game_dir)
    sink = SampleSink(game_dir)

    for i, frame in enumerate(VideoFrameSource(args.video)):
        if i % max(1, int(args.stride)) != 0:
            continue

        snap = ctrl.process_frame(
            frame,
            i,
            num_th=float(args.num_th),
            suit_th=float(args.suit_th),
            require_k=int(args.require_k),
        )

        # stocker les inconnus (option basique: si zone présente mais non stable)
        pairs = collect_card_patches(
            frame,
            ctrl.regions,
            pad=4,
            table_capture=ctrl.table_capture,
            offset=ctrl.last_offset,
        )
        for base_key, card_patch in pairs.items():
            patch_num = card_patch.number
            patch_suit = card_patch.suit
            if not is_card_present(patch_num):
                continue
            st = ctrl.state.cards.get(base_key)
            if not st or st.stable == 0:
                # pas encore reconnu → on garde un échantillon pour labellisation ultérieure
                sink.save_number(base_key, patch_num, i, template_set=card_patch.template_set)
                sink.save_suit(base_key, patch_suit, i, template_set=card_patch.template_set)

        # Affiche un résumé court
        pretty = ", ".join(
            [
                f"{k}:{v['value'] or '?'}-{v['suit'] or '?'}(s{v['stable']})"
                for k, v in sorted(snap.items())
            ]
        )
        print(f"frame {i:05d}: {pretty}")

    return 0


# --- Helpers: default video path + dedupe hash (utiles pour run_video_validate) ---


def _auto_video_for_game(game_dir: Path) -> Optional[Path]:
    """Retourne config/<game>/cards_video.{avi,mp4,mkv,mov} si présent; sinon None."""

    for ext in (".avi", ".mp4", ".mkv", ".mov"):
        p = game_dir / f"cards_video{ext}"
        if p.exists():
            return p
    return None


def _ahash(img: Image.Image, hash_size: int = 8) -> str:
    """Average-hash (8x8 par défaut) pour éviter de sauvegarder des doublons d'extraits."""

    g = img.convert("L").resize((hash_size, hash_size), Image.BILINEAR)
    arr = np.array(g, dtype=np.float32)
    mean = float(arr.mean())
    # bitstring stable
    return "".join("1" if v > mean else "0" for v in arr.flatten())


# ==============================
# Point d'entrée unifié
# ==============================

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Point d'entrée commun pour les CLIs de capture."""

    parsed = list(argv) if argv is not None else sys.argv[1:]
    # Heuristique simple : si --video est présent, on lance le mode vidéo,
    # sinon la validation sur image fixe.
    if "--video" in parsed:
        return int(main_video_validate(parsed))
    return int(main_cards_validate(parsed))


if __name__ == "__main__":
    raise SystemExit(main())
