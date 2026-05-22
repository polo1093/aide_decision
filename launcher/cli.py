"""Command-line parsing helpers for the launcher."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from launch_support import DEFAULT_SCAN_INTERVAL_MS
from objet.services.range_analyzer import POSITIONS as HERO_POSITIONS


DECISION_MODES = ("legacy", "pokermaster")
DEFAULT_HERO_POSITION = "BTN"


def parse_args(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="UI autour de Controller.run_cycle()")
    parser.add_argument("--interval", type=int, default=DEFAULT_SCAN_INTERVAL_MS, help="Intervalle entre deux scans en ms (minimum 25)")
    parser.add_argument("--game", help="Nom du jeu/profil dans config/ (sinon dernier profil utilise)")
    parser.add_argument("--list-games", action="store_true", help="Liste les profils disponibles puis quitte.")
    parser.add_argument("--snapshot", action="store_true", help="Execute un seul scan dans le terminal.")
    parser.add_argument(
        "--decision-mode",
        choices=DECISION_MODES,
        default="legacy",
        help="Moteur de decision a utiliser.",
    )
    parser.add_argument(
        "--hero-position",
        choices=HERO_POSITIONS,
        default=DEFAULT_HERO_POSITION,
        help="Position preflop hero utilisee par les ranges.",
    )
    args = parser.parse_args(raw_argv)
    args.decision_mode_explicit = any(
        arg == "--decision-mode" or arg.startswith("--decision-mode=")
        for arg in raw_argv
    )
    args.hero_position_explicit = any(
        arg == "--hero-position" or arg.startswith("--hero-position=")
        for arg in raw_argv
    )
    return args


def select_initial_decision_mode(
    cli_mode: Optional[str],
    interface_state: dict,
    *,
    cli_explicit: bool = False,
) -> str:
    if cli_explicit:
        return _normalise_decision_mode(cli_mode)
    return _normalise_decision_mode(interface_state.get("decision_mode") or cli_mode)


def _normalise_decision_mode(value: object) -> str:
    mode = str(value or "").strip()
    return mode if mode in DECISION_MODES else "legacy"


def select_initial_hero_position(
    cli_position: Optional[str],
    interface_state: dict,
    *,
    cli_explicit: bool = False,
) -> str:
    if cli_explicit:
        return _normalise_hero_position(cli_position)
    return _normalise_hero_position(interface_state.get("hero_position") or cli_position)


def _normalise_hero_position(value: object) -> str:
    position = str(value or "").strip().upper()
    return position if position in HERO_POSITIONS else DEFAULT_HERO_POSITION
