"""Entités décrivant les joueurs présents à la table."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Iterator, Optional

import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.calibration import bbox_from_region, load_coordinates

list_etat = ["No_start", "fold", "play", "paid"]
DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")

@dataclass
class Fond:
    coordinates_value: Optional[tuple[int, int, int, int]] = None
    amount: Optional[float] = None
    
    def reset(self) -> None:
        self.amount = None
    def __repr__(self) -> str:
        # repr compact, mais tu peux faire plus verbeux si tu veux
        return f"Fond(amount={self.amount})"  
    def __str__(self) -> str:
        return f"{self.amount:.2f}" if self.amount else "0"
    
             
@dataclass
class Players:
    
    coord_path: Path | str = DEFAULT_COORD_PATH
    player : list[Player] =  field(default_factory=list)
    nbr_player_active : int = 5
    nbr_player_start : int = 5
    
    def __post_init__(self) -> None:
        regions, templates_resolved, _ = load_coordinates(self.coord_path)
        if not self.player:
            self.player = [ Player(
                coordonate_money=bbox_from_region(regions.get(f"player_money_J{i}")),
                coordonate_etat=bbox_from_region(regions.get(f"player_state_J{i}")),
                ) for i in range(1,6)]
    
    def __iter__(self) -> Iterator[Player]:
        return iter(self.player)

    def __len__(self) -> int:
        return len(self.player)

    def __getitem__(self, index: int) -> Player:
        return self.player[index]   
    
    def reset(self) -> None:
        for p in self.player:
            p.reset()
    def new_round(self) -> None:
        for p in self.player:
            p.new_round()
            
    
    def cal_nbr_player_start(self)-> int:
        self.nbr_player_start = sum([self.player[i].active_at_start for i in range(5)])
    
    def cal_nbr_player_active(self)-> int:
        self.nbr_player_active = sum([self.player[i].is_activate() for i in range(5)])
    
    
    
    

@dataclass
class Player:
    coordonate_money: Optional[tuple[int, int, int, int]] = None
    coordonate_etat: Optional[tuple[int, int, int, int]] = None
    active_at_start: bool = True  # Indique si le joueur était actif au début de la main pas utiliser
    fond_start_Party: Optional[float] = 0
    fond: Fond = field(default_factory=Fond)
    etat : str = "play"
    etat_modified_this_round : bool = False
    
    def __post_init__(self) -> None:
        self.fond.coordinates_value = self.coordonate_money


    def is_activate(self) -> bool:
        return True if self.etat in  ["play" , "paid"] and self.active_at_start else False

    def reset(self) -> None:
        self.fond.reset()
        self.active_at_start = True
        self.continue_round = True
    
    def new_round(self):
        if self.etat_modified_this_round == False and self.etat == "play":
            self.etat = "fold"
        self.etat_modified_this_round = False
        if self.is_activate():
            self.etat = "play"
        
        
            
    
    def apply_scan(self, str_etat, money ) -> None :
        if money is not None:
            self.refresh_etat(str_etat, money)
            self.refresh_fond(money)
        if self.fond_start_Party == 0:
            self.active_at_start = False
        
    def refresh_etat(self, etat: str, money: float) -> None:
        if etat == "No_start":
            self.active_at_start = False
        if etat == "play":
            self.etat = "play"
            self.etat_modified_this_round = True
        existing = self.fond.amount
        if (existing is not None and money < existing) or etat == "paid":
            self.etat = "paid"
            self.etat_modified_this_round = True    
        if  etat == "fold":
            self.etat = "fold"
            self.etat_modified_this_round = True
            self.active_at_start = True
        if etat == "CHECK" :
            self.etat = "play"
            self.etat_modified_this_round = True           
            
    def refresh_fond(self, money: float) -> None:
        if self.fond_start_Party==0:
            self.fond_start_Party = money
        self.fond.amount = money
        
    def __repr__(self) -> str:
        """
        Repr au format dataclass classique, mais avec un champ dérivé supplémentaire:
        'fonds=<montant>'.
        """
        cls_name = self.__class__.__name__
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            parts.append(f"{f.name}={value!r}")
        # Champ dérivé supplémentaire
        parts.append(f"fonds={self.fond.amount!r}")
        return f"{cls_name}({', '.join(parts)})"
        


if __name__ == "__main__":
    ps = Players()
    p=Player()
    print(p)
    print(p.is_activate())
    print(ps.player[0])
    

__all__ = ["Player"]
