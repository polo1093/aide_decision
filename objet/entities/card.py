"""Entité unique représentant une carte scannée et sa normalisation."""
from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

from typing import Dict, List, Optional, Tuple

from pokereval.card import Card as PokerCard
import logging
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.calibration import Region, bbox_from_region, load_coordinates

LOGGER = logging.getLogger(__name__)

SUIT_ALIASES = {
    "hearts": "\u2665",
    "diamonds": "\u2666",
    "spades": "\u2660",
    "clubs": "\u2663",
    "heart": "\u2665",
    "diamond": "\u2666",
    "spade": "\u2660",
    "club": "\u2663",
}


CardBox = Tuple[int, int, int, int]


DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")


@dataclass
class Card:
    """Observation d'une carte et conversion vers l'objet PokerCard."""
    card_coordinates_value: Optional[tuple[int, int, int, int]] = None
    card_coordinates_suit: Optional[tuple[int, int, int, int]] = None
    template_set: Optional[str] = None
    value: Optional[str] = None
    suit: Optional[str] = None
    value_score: Optional[float] = None
    suit_score: Optional[float] = None
    poker_card: Optional[PokerCard] = None
    formatted: Optional[str] = None


    def scan(self) -> tuple[Optional[str], Optional[str]]:
        """
        Retourne la valeur brute scannée (value, suit).

        Utile pour debugger le flux OCR avant conversion en PokerCard.
        """
        return self.value, self.suit

    def apply_observation(
        self,
        value: Optional[str],
        suit: Optional[str],
        value_score: Optional[float] = None,
        suit_score: Optional[float] = None,
    ) -> None:
        """Applique une nouvelle observation et met à jour ."""
        self.value = value
        self.suit = suit
        self.value_score = value_score
        self.suit_score = suit_score
        if self.value and self.suit: 
            suit_sym = SUIT_ALIASES.get(self.suit, self.suit)
            formatted = f"{self.value}{suit_sym}"
            self.formatted = formatted
            self.poker_card = self._convert_string_to_pokercard(formatted)
        else:
            self.formatted = None
            self.poker_card = None
            
    def reset(self) -> None:
        """Réinitialise l'état de la carte."""
        self.value = None
        self.suit = None
        self.value_score = None
        self.suit_score = None
        self.poker_card = None
        self.formatted = None

    @staticmethod
    def _convert_string_to_pokercard(string_carte: Optional[str]) -> Optional[PokerCard]:
        """
        Convertit une chaîne '10♥' / 'A♠' en PokerCard (ou None si invalide).

        Mapping suits pokereval:
            1 -> spades (s)
            2 -> hearts (h)
            3 -> diamonds (d)
            4 -> clubs (c)
        """
        suit_dict = {
            "\u2660": 1,  # ♠
            "\u2665": 2,  # ♥
            "\u2666": 3,  # ♦
            "\u2663": 4,  # ♣
        }
        value_dict = {
            "2": 2,
            "3": 3,
            "4": 4,
            "5": 5,
            "6": 6,
            "7": 7,
            "8": 8,
            "9": 9,
            "10": 10,
            "J": 11,
            "Q": 12,
            "K": 13,
            "A": 14,
        }

        if string_carte in (None, "", "_"):
            return None

        string_carte = string_carte.strip()
        if not string_carte:
            return None

        # correction éventuelle si le scanner a renvoyé '0' au lieu de '10' en première position
        if string_carte[0] == "0" and len(string_carte) >= 2:
            original = string_carte
            corrected = "10" + string_carte[1:]
            LOGGER.debug(
                "Debug : La carte spécifiée '%s' est modifiée en '%s' pour correction.",
                original,
                corrected,
            )
            string_carte = corrected

        if len(string_carte) >= 2:
            value_part = string_carte[:-1]
            suit_part = string_carte[-1]
            value = value_dict.get(value_part)
            suit = suit_dict.get(suit_part)
            if value is not None and suit is not None:
                return PokerCard(value, suit)
            LOGGER.debug("Debug : La carte spécifiée '%s' n'est pas reconnue.", string_carte)
            return None

        LOGGER.debug("Debug : La carte spécifiée '%s' est trop courte.", string_carte)
        return None


@dataclass
class CardsState:
    """
    Regroupe les cartes du board et du joueur, avec coordonnées injectées.

    - `coord_path` permet de surcharger le fichier de coordonnées si besoin
      (par défaut : config/PMU/coordinates.json).
    - Si `board` / `me` ne sont pas fournis, ils sont construits automatiquement
      à partir de `load_coordinates(coord_path)`.
    """

    coord_path: Path | str = DEFAULT_COORD_PATH
    board: List[Card] = field(default_factory=list)
    me: List[Card] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Cas où on injecte manuellement des cartes : on ne touche à rien.
        if self.board and self.me:
            return

        regions, templates_resolved, _ = load_coordinates(self.coord_path)

        if not self.board:
            self.board = [
                Card(
                    card_coordinates_value=bbox_from_region(regions.get(f"board_card_{i}_number")),
                    card_coordinates_suit=bbox_from_region(regions.get(f"board_card_{i}_symbol")),
                    template_set=_template_set_for_card(
                        regions,
                        f"board_card_{i}_number",
                        f"board_card_{i}_symbol",
                    ),
                )
                for i in range(1, 6)
            ]

        if not self.me:
            self.me = [
                Card(
                    card_coordinates_value=bbox_from_region(regions.get(f"player_card_{i}_number")),
                    card_coordinates_suit=bbox_from_region(regions.get(f"player_card_{i}_symbol")),
                    template_set=_template_set_for_card(
                        regions,
                        f"player_card_{i}_number",
                        f"player_card_{i}_symbol",
                    ),
                )
                for i in range(1, 3)
            ]

    # --- API pratique pour le reste du code ----------------------------------
    def is_ready_for_cal(self) -> bool :
        for card  in self.me_cards():
            if card.poker_card is None:
                return False    
        return True
        
    def me_cards(self) -> List[Card]:
        """Retourne les entités Card du joueur (avec value/suit/poker_card)."""
        return self.me

    def board_cards(self) -> List[Card]:
        """Retourne les entités Card du board."""
        return self.board

    def reset(self) -> None:
        """Réinitialise l'état de toutes les cartes."""
        for card in self.me + self.board:
            card.reset()


def _template_set_from_region(region: Optional[Region]) -> Optional[str]:
    if region is None:
        return None
    value = region.meta.get("template_set")
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def _template_set_for_card(
    regions: Dict[str, Region],
    number_key: str,
    symbol_key: str,
) -> Optional[str]:
    tpl = _template_set_from_region(regions.get(number_key))
    if tpl:
        return tpl
    return _template_set_from_region(regions.get(symbol_key))


__all__ = ["Card", "CardsState"]


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(message)s")

    print("=== Tests manuels de Card ===")

    tests = [
        ("A", "hearts"),
        ("10", "spades"),
        ("J", "diamonds"),
        (None, "clubs"),   # valeur manquante
        ("Q", None),       # couleur manquante
    ]

    for idx, (val, suit) in enumerate(tests, start=1):
        c = Card()
        c.apply_observation(value=val, suit=suit)
        print(f"Test {idx} : value={val!r}, suit={suit!r}")
        print(f"  formatted   = {c.formatted()!r}")
        print(f"  poker_card  = {c.poker_card!r}")
        print(f"  raw scan    = {c.scan()!r}")
        print("-" * 40)

    print("Vous pouvez également passer une carte en argument, ex :")
    print("  python card.py 'A♥'")

    if len(sys.argv) > 1:
        raw = sys.argv[1]
        print(f"\n=== Conversion directe depuis l'argument CLI : {raw!r} ===")
        pc = Card._convert_string_to_pokercard(raw)
        print("PokerCard =>", pc)

    cards_state = CardsState()
    print(cards_state.board[0])
