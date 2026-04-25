"""Service d'orchestration autour de l'état de la table de jeu."""


from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from objet.entities.buttons import Buttons
from objet.entities.card import CardsState
from objet.entities.player import Fond , Players
from objet.utils.capture import CaptureState
from objet.scanner.scan import ScanTable
from objet.utils.calibration import load_coordinates, bbox_from_region
from objet.utils.logging_config import get_logger
DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")


LOGGER = get_logger(__name__)


    

@dataclass
class Table:
    """Réunit Les éléments à scanner et service de scan."""
    
    coord_path: Path | str = DEFAULT_COORD_PATH
    cards: CardsState = field(default_factory=CardsState)
    buttons: Buttons = field(default_factory=Buttons)
    captures: CaptureState = field(default_factory=CaptureState)
    scan: ScanTable = field(default_factory=ScanTable)
    pot: Fond = field(default_factory=Fond)
    new_party_flag: bool = False
    players : Players = field(default_factory=Players)
    
    
    def __post_init__(self) -> None:
        regions, _, _ = load_coordinates(self.coord_path)
        self.pot.coordinates_value = bbox_from_region(regions.get("pot"))
        
        
    def launch_scan(self) -> bool:
        LOGGER.info("debut scan_table")
        if not self.scan.test_scan():
            LOGGER.warning("SKIP table_introuvable status=scan_failed")
            return False
        
        # --- Main héros (2 cartes) ---
        for card in self.cards.me:
            value, suit, confidence_value, confidence_suit = self.scan.scan_carte(
                position_value=card.card_coordinates_value,
                position_suit=card.card_coordinates_suit,
                template_set=card.template_set
            )

            card.apply_observation(
                value=value,
                suit=suit,
                value_score=confidence_value,
                suit_score=confidence_suit,
            )
            LOGGER.debug(
                "SCAN carte zone=main value=%s suit=%s score_value=%.3f score_suit=%.3f",
                value,
                suit,
                confidence_value,
                confidence_suit,
            )
        
        for card in self.cards.board:
            value, suit, confidence_value, confidence_suit = self.scan.scan_carte(
                position_value=card.card_coordinates_value,
                position_suit=card.card_coordinates_suit,
                template_set=card.template_set,
            )
            if value is None and suit is None:
                continue
            card.apply_observation(
                value=value,
                suit=suit,
                value_score=confidence_value,
                suit_score=confidence_suit,
            )
            LOGGER.debug(
                "SCAN carte zone=board value=%s suit=%s score_value=%.3f score_suit=%.3f",
                value,
                suit,
                confidence_value,
                confidence_suit,
            )
        for player in self.players.player:
            etat , money = self.scan.scan_player(
                position_money= player.fond.coordinates_value,
                position_etat= player.coordonate_etat )
            player.apply_scan(etat,money)
            LOGGER.debug("SCAN joueur etat=%s fond=%s", etat, money)
            
        for b in self.buttons:
            texte = self.scan.scan_bouton(position= b.coordonate)
            b.apply_scan(texte)
            LOGGER.debug("SCAN bouton texte=%s enabled=%s value=%s", texte, b.enabled, b.value)
            

        self.pot.amount = self.scan.scan_money(self.pot.coordinates_value)
        LOGGER.info(
            "fin scan_table status=ok main=%s board=%s joueurs=%s boutons=%s pot=%s",
            _count_detected_cards(self.cards.me_cards()),
            _count_detected_cards(self.cards.board_cards()),
            len(self.players.player),
            len(list(self.buttons)),
            self.pot.amount,
        )
        return True

    def New_Party(self)-> None:
        """Réinitialise l'état de la Table. et fait remonter un événement."""
        LOGGER.info("RESET table raison=nouvelle_partie")
        self.cards.reset()
        self.players.reset()
        self.new_party_flag = True
        
    
        
if __name__ == "__main__":
    # Petit stub de test local
    table = Table()
    table.launch_scan()
    print("Cartes joueur:", table.cards.me_cards())
    

__all__ = ["Table"]


def _count_detected_cards(cards) -> int:
    return sum(1 for card in cards if getattr(card, "formatted", None))
