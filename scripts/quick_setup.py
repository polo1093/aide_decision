#!/usr/bin/env python3
"""quick_setup.py — pipeline de configuration rapide pour la capture des cartes.

Ce script enchaîne les étapes manuelles existantes :
  1. Éditer les zones via l'UI CustomTkinter.
  2. Capturer des frames plein écran depuis une vidéo de test.
  3. Identifier/labelliser les cartes manquantes.
  4. Valider la capture complète sur une vidéo.

Chaque étape peut être sautée avec --skip-*."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple, cast

# Monkey-patch newer OpenCV builds that no longer expose the legacy constants so PyScreeze still loads.
try:
    import cv2
except ImportError:
    cv2 = None
else:
    for legacy, modern in (
        ("CV_LOAD_IMAGE_COLOR", "IMREAD_COLOR"),
        ("CV_LOAD_IMAGE_GRAYSCALE", "IMREAD_GRAYSCALE"),
    ):
        if not hasattr(cv2, legacy) and hasattr(cv2, modern):
            setattr(cv2, legacy, getattr(cv2, modern))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.scanner.cards_recognition import ROOT_TEMPLATE_SET, TemplateIndex


EXPECTED_NUMBERS: Tuple[str, ...] = (
    "A",
    "K",
    "Q",
    "J",
    "10",
    "9",
    "8",
    "7",
    "6",
    "5",
    "4",
    "3",
    "2",
)
EXPECTED_SUITS: Tuple[str, ...] = ("hearts", "diamonds", "clubs", "spades")


def _print_header(title: str) -> None:
    line = "=" * max(10, len(title) + 4)
    print(f"\n{line}\n  {title}\n{line}")


def _run_zone_editor(game: str, config_root: Path) -> int:
    from position_zones_ctk import ZoneEditorCTK

    app = ZoneEditorCTK(base_dir=str(config_root))
    if game:
        try:
            app.game_var.set(game)
            app._on_select_game(game)  # type: ignore[attr-defined]
            print(f"ZoneEditor prêt sur le jeu '{game}'. Fermez la fenêtre pour continuer…")
        except Exception as exc:  # pragma: no cover - dépend de l'état local
            print(f"[WARN] Impossible de précharger le jeu '{game}': {exc}")
    app.run()
    return 0


def _run_capture_frames(game_dir: Path, video: Optional[str], interval: float, out_dir: Optional[Path]) -> int:
    from Crop_Video_Frames import main as crop_main

    argv: List[str] = ["--game-dir", str(game_dir)]
    if video:
        argv += ["--video", video]
    if interval is not None:
        argv += ["--interval", str(interval)]
    if out_dir is not None:
        argv += ["--out", str(out_dir)]
    return int(crop_main(argv))


def _run_identify(game: str, screens_dir: Optional[Path], threshold: float, strict: float, trim: int, force_all: bool) -> int:
    from identify_card import main as identify_main

    argv: List[str] = ["--game", game, "--threshold", str(threshold), "--strict", str(strict), "--trim", str(trim)]
    if screens_dir is not None:
        argv += ["--screens-dir", str(screens_dir)]
    if force_all:
        argv.append("--force-all")
    return int(identify_main(argv))


def _run_capture_video(
    game: str,
    game_dir: Path,
    video: Optional[str],
    stride: int,
    num_th: float,
    suit_th: float,
    require_k: int,
) -> int:
    import importlib

    module = importlib.import_module("capture_cards")

    capture_entry: Callable[[Sequence[str]], int]
    if hasattr(module, "main"):
        capture_entry = cast(Callable[[Sequence[str]], int], getattr(module, "main"))
    elif hasattr(module, "main_video_validate"):
        capture_entry = cast(
            Callable[[Sequence[str]], int], getattr(module, "main_video_validate")
        )
    else:  # pragma: no cover - dépend de l'environnement utilisateur
        raise SystemExit("capture_cards ne fournit ni main() ni main_video_validate().")

    argv: List[str] = [
        "--game",
        game,
        "--game-dir",
        str(game_dir),
        "--stride",
        str(stride),
        "--num-th",
        str(num_th),
        "--suit-th",
        str(suit_th),
        "--require-k",
        str(require_k),
    ]
    if video:
        argv += ["--video", video]
    else:
        raise SystemExit("La validation vidéo nécessite --video.")
    return int(capture_entry(argv))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assistant de configuration rapide (zones -> captures -> cartes -> validation)")
    parser.add_argument("--game", default="PMU", help="Nom du jeu (dossier dans config/)")
    parser.add_argument("--config-root", help="Chemin vers le dossier config/ (défaut: auto)")
    parser.add_argument("--video", help="Vidéo utilisée pour le crop et la validation")
    parser.add_argument("--screens-dir", help="Dossier de sortie des captures (défaut: config/<game>/entrainement/screens)")
    parser.add_argument("--capture-interval", type=float, default=3.0, help="Intervalle (s) entre deux captures vidéo")
    parser.add_argument("--identify-threshold", type=float, default=0.92, help="Seuil reco acceptée")
    parser.add_argument("--identify-strict", type=float, default=0.985, help="Seuil autoskip strict")
    parser.add_argument("--identify-trim", type=int, default=6, help="Rognage autour des patches (px)")
    parser.add_argument("--identify-force-all", action="store_true", help="Forcer l'UI sur toutes les cartes")
    parser.add_argument("--capture-stride", type=int, default=3, help="Traiter un frame sur N pour la validation vidéo")
    parser.add_argument("--capture-num-th", type=float, default=0.65, help="Seuil reconnaissance des valeurs")
    parser.add_argument("--capture-suit-th", type=float, default=0.65, help="Seuil reconnaissance des couleurs")
    parser.add_argument("--capture-require-k", type=int, default=2, help="Frames nécessaires pour stabiliser")
    parser.add_argument("--skip-zone-editor", action="store_true", help="Sauter l'étape d'édition des zones")
    parser.add_argument("--skip-capture", action="store_true", help="Sauter l'étape de captures vidéo")
    parser.add_argument("--skip-identify", action="store_true", help="Sauter l'étape d'identification des cartes")
    parser.add_argument("--skip-capture-validation", action="store_true", help="Sauter la validation capture")
    parser.add_argument("--continue-on-error", action="store_true", help="Continuer même si une étape échoue")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    config_root = Path(args.config_root).resolve() if args.config_root else (PROJECT_ROOT / "config").resolve()
    game_dir = (config_root / args.game).resolve()
    if not game_dir.exists():
        print(f"ERREUR: dossier du jeu introuvable ({game_dir})")
        return 2

    screens_dir = Path(args.screens_dir).resolve() if args.screens_dir else (game_dir / "entrainement" / "screens")

    steps: List[Tuple[str, Callable[[], int]]] = []
    if not args.skip_zone_editor:
        steps.append(("Édition des zones", lambda: _run_zone_editor(args.game, config_root)))
    if not args.skip_capture:
        steps.append((
            "Captures vidéo",
            lambda: _run_capture_frames(
                game_dir,
                args.video,
                float(args.capture_interval),
                screens_dir,
            ),
        ))
    if not args.skip_identify:
        steps.append((
            "Identification des cartes",
            lambda: _run_identify(
                args.game,
                screens_dir,
                float(args.identify_threshold),
                float(args.identify_strict),
                int(args.identify_trim),
                bool(args.identify_force_all),
            ),
        ))
    if not args.skip_capture_validation:
        if args.video:
            steps.append((
                "Validation capture vidéo",
                lambda: _run_capture_video(
                    args.game,
                    game_dir,
                    args.video,
                    int(args.capture_stride),
                    float(args.capture_num_th),
                    float(args.capture_suit_th),
                    int(args.capture_require_k),
                ),
            ))
        else:
            # Mode "je clique sur Exécuter" sans arguments :
            # on ignore simplement la validation vidéo.
            print("[INFO] Aucune vidéo (--video) fournie : étape 'Validation capture vidéo' sautée.")


    status = 0
    for title, func in steps:
        _print_header(title)
        try:
            status = func()
        except SystemExit as exc:
            # Afficher le message associé au SystemExit s'il existe
            msg = str(exc)
            if msg:
                print(f"[ERREUR] {title}: {msg}")
            status = int(exc.code) if isinstance(exc.code, int) else 1
        except Exception as exc:  # pragma: no cover - dépend de l'exécution temps réel
            print(f"[ERREUR] {title}: {exc}")
            status = 1
        if status != 0:
            print(f"[ECHEC] {title} (code {status})")
            if not args.continue_on_error:
                break


    _report_missing_cards(game_dir)

    return status


def _report_missing_cards(game_dir: Path) -> None:
    cards_root = game_dir / "cards"
    if not cards_root.exists():
        print("[INFO] Aucun dossier 'cards' trouvé pour ce jeu — impossible de vérifier les gabarits.")
        return

    print(
        "[INFO] Organisation attendue : cards/<ensemble>/{numbers,suits}/ (ex: 'board', 'hand')."
    )

    idx = TemplateIndex(cards_root)
    idx.load()
    sets = idx.available_sets()
    if not sets:
        sets = [idx.default_set]

    any_missing = False
    for set_name in sets:
        template_set = None if set_name in (None, ROOT_TEMPLATE_SET) else set_name
        missing = idx.check_missing(
            EXPECTED_NUMBERS,
            EXPECTED_SUITS,
            template_set=template_set,
        )
        missing_cards = idx.missing_cards(
            EXPECTED_NUMBERS,
            EXPECTED_SUITS,
            template_set=template_set,
        )

        if not missing["numbers"] and not missing["suits"] and not missing_cards:
            continue

        if not any_missing:
            _print_header("Gabarits de cartes manquants")
            any_missing = True

        label = template_set or "défaut"
        print(f"Ensemble '{label}':")
        if missing["numbers"]:
            print("  Numbers manquants:", ", ".join(missing["numbers"]))
        if missing["suits"]:
            print("  Symboles manquants:", ", ".join(missing["suits"]))
        if missing_cards:
            print("  Combinaisons impossibles:")
            for combo in missing_cards:
                print(f"    - {combo}")

    if not any_missing:
        print("[OK] Tous les gabarits de cartes attendus sont présents dans chaque ensemble.")


if __name__ == "__main__":
    raise SystemExit(main())
