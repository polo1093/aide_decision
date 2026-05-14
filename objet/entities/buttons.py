"""Entités décrivant les boutons d'action disponibles sur la table."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator, Optional

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
from objet.utils.calibration import bbox_from_region, load_coordinates   
import re
DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")

list_etat_button= ["check", "relance", "mise", "fold", "paie", "all-in"  ]

@dataclass
class Buttons:
    """Collection utilitaire regroupant l'ensemble des boutons connus."""
    coord_path: Path | str = DEFAULT_COORD_PATH
    button : list[Button] = field(default_factory=list)
    

    def __post_init__(self) -> None:
        regions, templates_resolved, _ = load_coordinates(self.coord_path)
        if not self.button:
            self.button = [ Button(
                coordonate=bbox_from_region(regions.get(f"button_{i}")),
                ) for i in range(1,4)]
    
    def __iter__(self) -> Iterator[Button]:
        return iter(self.button)

    def __len__(self) -> int:
        return len(self.button)

    def __getitem__(self, index: int) -> Button:
        return self.button[index]   
    
    def one_is_activate(self) -> bool:
        for b in self.button:
            if b.is_activate():
                return True
        return False

    def has_active_state(self, *states: str) -> bool:
        expected = {state.lower() for state in states}
        return any(
            b.is_activate() and b.etat.lower() in expected
            for b in self.button
        )

    def has_free_action(self) -> bool:
        return self.has_active_state("check")

    def has_aggressive_action(self) -> bool:
        return self.has_active_state("mise", "relance", "all-in")

    def min_value(self)-> float:
        if self.has_free_action():
            return 0.0

        min = 1000
        for b in self.button :  
            if b.is_activate() and b.value != 0:
                if b.value < min:
                    min = b.value      
        return 0 if min == 1000 else min
    
    def reset_all(self) -> None:
        """Réinitialise l'ensemble des boutons."""
        for button in self:
            button.reset()
            
@dataclass
class Button:
    """Représentation d'un bouton unique présent sur l'interface."""

    texte: str =""
    etat : str =""
    value: float = 0.0
    coordonate: Optional[tuple[int, int, int, int]] = None
    enabled: bool = False
    score: float = 0.0



    def reset(self) -> None:
        """Réinitialise complètement l'état du bouton."""
        self.enabled = False
        self.score = 0.0
        self.texte = ""
        self.etat = ""
        self.value = 0.0
        
    def is_activate(self) -> bool:
        return self.enabled
        
    def apply_scan(self, texte)-> None:
        if not texte:
            self.reset()
            return 
        self.texte=texte
        etat = one_element_in_str(list_etat_button,texte)
        if etat:
            self.enabled = True
            self.etat = etat
            self.value =  float_in_str(texte) 
        else :
            self.enabled = False
            self.etat = ""
            self.value = 0.0
           
    
    
    
def float_in_str(texte: str) -> float:
    """Extrait la première valeur numérique d'une chaîne et la retourne en float.
    Retourne 0.0 si aucune valeur trouvée ou en cas d'erreur."""
    if not texte:
        return 0.0

    m = re.search(r'[-+]?\d+(?:[.,]\d+)?', texte)
    if not m:
        return 0
    else:
        s = m.group(0).replace(',', '.')
        try:
            v = float(s)
        except ValueError:
            v = 0
    return v 



def _matches_with_one_diff(candidate: str, text: str) -> bool:
    n = len(candidate)
    m = len(text)
    if m < n:
        return False

    # On teste toutes les fenêtres de longueur n dans `text`
    for i in range(m - n + 1):
        segment = text[i:i+n]
        # Nombre de positions où les caractères diffèrent
        diffs = sum(1 for a, b in zip(candidate, segment) if a != b)
        if diffs <= 1:
            return True
    return False


def one_element_in_str(list_str, texte: str):
    for cand in list_str:
        if _matches_with_one_diff(cand, texte):
            return cand
    return None


__all__ = ["Button", "Buttons"]


if __name__ == "__main__":
    bs = Buttons()
    b=Button()
    print(b)
    print(b.is_activate())
    print(bs.button[0])
