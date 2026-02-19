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
DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")


    

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
       
        if not self.scan.test_scan():
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
        for player in self.players.player:
            etat , money = self.scan.scan_player(
                position_money= player.fond.coordinates_value,
                position_etat= player.coordonate_etat )
            player.apply_scan(etat,money)
            
        for b in self.buttons:
            texte = self.scan.scan_bouton(position= b.coordonate)
            b.apply_scan(texte)
            

                
        self.pot.amount = self.scan.scan_money(self.pot.coordinates_value)
        return True

    def New_Party(self)-> None:
        """Réinitialise l'état de la Table. et fait remonter un événement."""
        self.cards.reset()
        self.players.reset()
        self.new_party_flag = True
        
    
        
if __name__ == "__main__":
    # Petit stub de test local
    table = Table()
    table.launch_scan()
    print("Cartes joueur:", table.cards.me_cards())
    

__all__ = ["Table"]
