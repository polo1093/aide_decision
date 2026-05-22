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

BUTTON_STATE_ALIASES = {
    "check": "check",
    "relance": "relance",
    "raise": "relance",
    "mise": "mise",
    "bet": "mise",
    "fold": "fold",
    "paie": "paie",
    "call": "paie",
    "all-in": "all-in",
    "allin": "all-in",
}
list_etat_button = list(BUTTON_STATE_ALIASES)

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

    def has_call_action(self) -> bool:
        return self.has_active_state("paie")

    def min_value(self)-> float:
        if self.has_free_action():
            return 0.0

        min_value = float("inf")
        for b in self.button :  
            if b.is_activate() and b.etat.lower() == "paie" and b.value != 0:
                if b.value < min_value:
                    min_value = b.value
        return 0 if min_value == float("inf") else min_value
    
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
            self.etat = BUTTON_STATE_ALIASES.get(etat, etat)
            self.value =  float_in_str(texte, state=self.etat) 
        else :
            self.enabled = False
            self.etat = ""
            self.value = 0.0
           
    
    
    
def float_in_str(texte: str, *, state: str = "") -> float:
    """Extrait une valeur numérique d'une chaîne bouton et la retourne en float.
    Retourne 0.0 si aucune valeur trouvée ou en cas d'erreur."""
    if not texte:
        return 0.0

    if state.lower() in {"check", "fold"}:
        return 0.0

    cleaned = re.sub(r"\bf\s*\d+\b", " ", texte, flags=re.IGNORECASE)
    grouped = r"(?<![A-Za-z0-9])[-+]?\d+(?:\s+\d{3})+(?:[.,]\d+)?(?![A-Za-z0-9])"
    plain = r"(?<![A-Za-z0-9])[-+]?\d+(?:[.,]\d+)?(?![A-Za-z0-9])"
    matches = re.findall(f"{grouped}|{plain}", cleaned)
    if not matches:
        return 0.0

    token = matches[-1].strip()
    has_currency_symbol = any(symbol in texte for symbol in ("$", "€", "£", "â‚¬", "Â£"))
    if (
        state.lower() == "paie"
        and not has_currency_symbol
        and re.fullmatch(r"[458]\d{2}", token)
        and not re.fullmatch(r"[0]+", token[1:])
    ):
        token = token[1:]

    token = re.sub(r"(?<!\d)5\s+(?=\d{1,3}(?:\s+\d{3})+(?:[.,]\d+)?\b)", "", token)
    token = re.sub(r"(?<!\d)5(?=\d{1,3}(?:\s+\d{3})+(?:[.,]\d+)?\b)", "", token)
    s = token.replace(" ", "").replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0



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
    text = str(texte).lower()
    for cand in list_str:
        if cand.lower() in text:
            return cand
    for cand in list_str:
        if _matches_with_one_diff(cand.lower(), text):
            return cand
    return None


__all__ = ["Button", "Buttons"]


if __name__ == "__main__":
    bs = Buttons()
    b=Button()
    print(b)
    print(b.is_activate())
    print(bs.button[0])
