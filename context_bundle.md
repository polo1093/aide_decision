# Bundle — aide_decission
_Généré le 2026-04-25 12:34:15_

## Fichiers

### folder_tool/__init__.py
```python

```
### folder_tool/timer.py
```python
import time


class Timer():
    """Timer used to check whether a waiting period has passed.

    Args:
        time_wait (float): Duration to wait in seconds.

    Returns:
        bool: True if the timer has expired.
    """
    def __init__(self,time_wait):
        self.start_time = time.perf_counter()
        self.time_wait = time_wait
    
    def is_expire(self):
        return time.perf_counter()-self.start_time >= self.time_wait    
    
    def is_running(self):
        return time.perf_counter()-self.start_time < self.time_wait
    
    def refresh(self,time_wait=0):
        if time_wait > 0: 
            self.time_wait = time_wait
        self.start_time = time.perf_counter()




```
### launch.py
```python

"""
UI simple pour exécuter périodiquement Controller.main()
=======================================================

- Boucle Tkinter non bloquante (`after`), Start/Stop/Snapshot.
- Intervalle de rafraîchissement paramétrable.
- On instancie directement Controller, sans import dynamique.
- On affiche directement la chaîne renvoyée par Controller.main().

Raccourcis clavier
------------------
- F5   : Start
- F6   : Snapshot (un seul appel à main())
- Échap: Stop
"""

from __future__ import annotations
import argparse
import time
from typing import Optional

import tkinter as tk
from tkinter import ttk

from objet.services.controller import Controller   # <--- IMPORTANT : import direct
from objet.utils.logging_config import (
    configure_logging,
    get_logger,
    log_path_value,
    session_log,
)


logger = get_logger(__name__)


class App(tk.Tk):
    def __init__(self, controller: Controller, scan_interval_ms: int = 1000):
        super().__init__()

        self.title("Live Table – Controller UI")
        self.geometry("880x640")
        self.minsize(780, 520)

        # Backend
        self.controller = controller

        # Orchestration
        self.scanning = False
        self.scan_interval_ms = scan_interval_ms
        self._last_tick_t: Optional[float] = None

        # Perf
        self.last_call_ms: Optional[float] = None
        self.fps: Optional[float] = None

        # UI
        self._build()
        self._layout()
        self._bind_keys()

        self._set_text("Prêt. Appuie sur F5 ou sur ▶ Start.")

    # ---------- Construction UI ----------

    def _build(self):
        # Barre supérieure
        self.frm_top = ttk.Frame(self)
        self.btn_start = ttk.Button(self.frm_top, text="▶ Start", command=self.start_scan)
        self.btn_stop = ttk.Button(self.frm_top, text="⏸ Stop", command=self.stop_scan)
        self.btn_snap = ttk.Button(self.frm_top, text="📸 Snapshot", command=self.snapshot_once)
        self.lbl_interval = ttk.Label(self.frm_top, text="Interval (ms):")
        self.var_interval = tk.StringVar(value=str(self.scan_interval_ms))
        self.ent_interval = ttk.Entry(self.frm_top, width=6, textvariable=self.var_interval)
        self.lbl_status = ttk.Label(self.frm_top, text="Ready.", width=30, anchor="w")

        # Zone centrale texte + scroll
        self.frm_center = ttk.Frame(self)
        self.txt = tk.Text(
            self.frm_center,
            height=26,
            wrap="none",
            font=("Consolas", 12),
            state="disabled",
        )
        self.scroll = ttk.Scrollbar(
            self.frm_center,
            orient="vertical",
            command=self.txt.yview
        )
        self.txt.configure(yscrollcommand=self.scroll.set)

        # Barre inférieure (perf)
        self.frm_bottom = ttk.Frame(self)
        self.var_perf = tk.StringVar(value="scan: — ms | fps: —")
        self.lbl_perf = ttk.Label(self.frm_bottom, textvariable=self.var_perf)

    def _layout(self):
        # Top
        self.frm_top.pack(side="top", fill="x", padx=10, pady=8)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop.pack(side="left", padx=(0, 12))
        self.btn_snap.pack(side="left", padx=(0, 18))
        self.lbl_interval.pack(side="left")
        self.ent_interval.pack(side="left", padx=(6, 18))
        self.lbl_status.pack(side="left", padx=6)

        # Centre
        self.frm_center.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 6))
        self.txt.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        # Bottom
        self.frm_bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.lbl_perf.pack(side="left")

    def _bind_keys(self):
        # IMPORTANT : ne pas utiliser `_bind` (réservé par tkinter)
        self.bind("<Escape>", lambda e: self.stop_scan())
        self.bind("<F5>", lambda e: self.start_scan())
        self.bind("<F6>", lambda e: self.snapshot_once())
        self.ent_interval.bind("<Return>", lambda e: self._update_interval())

    # ---------- Helpers UI ----------

    def _set_text(self, text: str):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")

    def _update_interval(self):
        try:
            v = int(self.var_interval.get())
            self.scan_interval_ms = max(25, min(2000, v))
        except Exception:
            self.scan_interval_ms = 1000
            self.var_interval.set(str(self.scan_interval_ms))

    # ---------- Orchestration ----------

    def start_scan(self):
        self._update_interval()
        self.scanning = True
        self.lbl_status.configure(text="Scanning…")
        self._last_tick_t = time.time()
        logger.info("debut scan_continu interval_ms=%s", self.scan_interval_ms)
        self.after(self.scan_interval_ms, self._tick)

    def stop_scan(self):
        if self.scanning:
            logger.info("fin scan_continu last_ms=%s", _fmt_optional_float(self.last_call_ms))
        self.scanning = False
        self.lbl_status.configure(text="Stopped.")

    def snapshot_once(self):
        """
        Un seul appel à Controller.main(), sans boucle continue.
        """
        logger.info("debut snapshot")
        t0 = time.perf_counter()
        try:
            out = self.controller.main()
        except Exception as exc:
            self._handle_controller_exception(context="Snapshot", error=exc)
            raise

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.last_call_ms = dt_ms
        self.fps = None

        text = out if isinstance(out, str) else repr(out)
        self._set_text(text)

        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: —")
        self.lbl_status.configure(text="Snapshot done.")
        logger.info("fin snapshot status=ok duree_ms=%.1f", dt_ms)

    def _tick(self):
        """
        Boucle périodique : appelle Controller.main() toutes les X ms.
        """
        if not self.scanning:
            return

        t0 = time.perf_counter()
        try:
            out = self.controller.main()
        except Exception as exc:
            self._handle_controller_exception(context="Scan continu", error=exc)
            raise
        else:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.last_call_ms = dt_ms

            # FPS estimé sur la boucle
            now = time.time()
            if self._last_tick_t is not None:
                dt_s = max(now - self._last_tick_t, 1e-6)
                self.fps = 1.0 / dt_s
            else:
                self.fps = None
            self._last_tick_t = now

            text = out if isinstance(out, str) else repr(out)
            self._set_text(text)

            fps_txt = f"{self.fps:.1f}" if self.fps else "—"
            self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: {fps_txt}")
            self.lbl_status.configure(text="OK.")

        if self.scanning:
            self.after(self.scan_interval_ms, self._tick)

    def _handle_controller_exception(self, context: str, error: Exception):
        """Affiche l'erreur côté UI et loggue le détail pour la console."""
        self.last_call_ms = None
        self.fps = None
        self._set_text(f"Erreur Controller.main(): {error}")
        self.var_perf.set("scan: — ms | fps: —")
        self.lbl_status.configure(text="Erreur controller.")
        logger.exception("ARRET - erreur controller contexte=%s error=%s", context, error)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="UI simple autour de Controller.main()")
    ap.add_argument(
        "--interval",
        type=int,
        default=1000,
        help="Intervalle entre deux appels à main() en ms (25..2000)",
    )
    ap.add_argument(
        "--snapshot",
        action="store_true",
        help="Exécute un seul Controller.main() dans le terminal, sans ouvrir l'interface.",
    )
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging()
    with session_log("interface") as log_file:
        logger.info(
            "debut interface interval_ms=%s log=%s",
            args.interval,
            log_path_value(log_file),
        )
        controller = Controller()
        if args.snapshot:
            print(controller.main())
            logger.info("fin snapshot_cli status=ok log=%s", log_path_value(log_file))
            return
        app = App(controller=controller, scan_interval_ms=args.interval)
        app.mainloop()
        logger.info("fin interface status=closed log=%s", log_path_value(log_file))


def _fmt_optional_float(value: Optional[float]) -> str:
    if value is None:
        return "None"
    return f"{value:.1f}"


if __name__ == "__main__":
    main()

```
### objet/__init__.py
```python
"""Paquetage structuré en entités, services et utilitaires."""

__all__ = ["entities", "services", "utils"]

```
### objet/entities/__init__.py
```python
"""Entités de base manipulées par les services du projet."""
from .buttons import  Buttons
from .card import Card
from .player import Player

__all__ = [
    "Buttons",
    "CardObservation",
    "CardSlot",
    "convert_card",
    "Player",
]

```
### objet/entities/buttons.py
```python
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

    def min_value(self)-> float:
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

```
### objet/entities/card.py
```python
"""Entité unique représentant une carte scannée et sa normalisation."""
from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

from typing import Dict, List, Optional, Tuple

from pokereval.card import Card as PokerCard
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.calibration import Region, bbox_from_region, load_coordinates
from objet.utils.logging_config import configure_logging, get_logger

LOGGER = get_logger(__name__)

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
            LOGGER.debug("CORRECTION carte old=%s->%s", original, corrected)
            string_carte = corrected

        if len(string_carte) >= 2:
            value_part = string_carte[:-1]
            suit_part = string_carte[-1]
            value = value_dict.get(value_part)
            suit = suit_dict.get(suit_part)
            if value is not None and suit is not None:
                return PokerCard(value, suit)
            LOGGER.debug("SKIP carte_non_reconnue value=%s", string_carte)
            return None

        LOGGER.debug("SKIP carte_trop_courte value=%s", string_carte)
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

    configure_logging()

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

```
### objet/entities/player.py
```python
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
        self.fond_start_Party = 0
        self.etat = "play"
        self.etat_modified_this_round = False
    
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

```
### objet/scanner/__init__.py
```python
# -*- coding: utf-8 -*-
from .scan import ScanTable

```
### objet/scanner/amount_ocr.py
```python
"""OCR utilities for reading amounts and short button texts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Compatibilité Pillow >= 10 pour EasyOCR
# ---------------------------------------------------------------------------
# Certaines versions d'EasyOCR appellent Image.ANTIALIAS, qui n'existe plus
# dans Pillow 10+. On recrée donc cet attribut en le pointant vers LANCZOS.
if not hasattr(Image, "ANTIALIAS"):
    try:
        # Pillow 10+: filtres dans Image.Resampling
        Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
    except Exception:
        # Fallback : la plupart des versions exposent encore Image.LANCZOS
        if hasattr(Image, "LANCZOS"):
            Image.ANTIALIAS = Image.LANCZOS  # type: ignore[attr-defined]

PatchType = Union[np.ndarray, Image.Image]


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into a single space."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _strip_currency_symbols(text: str) -> str:
    """Remove common currency symbols and non-breaking spaces."""
    replacements = {
        "\xa0": " ",
        "€": " ",
        "$": " ",
        "£": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _extract_numeric_tokens(text: str) -> list[str]:
    """Return candidate numeric tokens from an OCR string."""
    return re.findall(r"[0-9]+(?:[.,][0-9]+)*", text)


@dataclass
class OcrEngine:
    """Lightweight OCR engine for amounts and short texts (buttons)."""

    lang: str = "fr"
    _reader: Optional[object] = None

    def _ensure_reader(self) -> None:
        """Lazily create the OCR backend (EasyOCR Reader or similar)."""
        if self._reader is not None:
            return

        import easyocr  # import différé pour ne pas charger EasyOCR inutilement

        langs = [self.lang]
        if "en" not in langs:
            langs.append("en")
        self._reader = easyocr.Reader(langs)

    def _to_pil(self, patch: PatchType) -> Image.Image:
        """Convert any supported input (np.ndarray BGR or PIL.Image) to a PIL RGB image."""
        if isinstance(patch, Image.Image):
            return patch.convert("RGB")

        if isinstance(patch, np.ndarray):
            if patch.ndim == 2:
                rgb = np.stack([patch] * 3, axis=-1)
            elif patch.ndim == 3 and patch.shape[2] == 3:
                # BGR -> RGB
                rgb = patch[:, :, ::-1]
            else:
                raise ValueError("Unsupported numpy patch shape")
            return Image.fromarray(rgb.astype(np.uint8), mode="RGB")

        raise TypeError("Unsupported patch type")

    def read_text(
        self,
        patch: PatchType,
        *,
        normalize_whitespace: bool = True,
    ) -> tuple[Optional[str], float]:
        """Read raw text from an image patch."""
        self._ensure_reader()
        pil_image = self._to_pil(patch)

        if pil_image.width == 0 or pil_image.height == 0:
            return None, 0.0

        np_image = np.array(pil_image)
        results = self._reader.readtext(np_image, detail=1)
        if not results:
            return None, 0.0

        texts = [text for _, text, conf in results if text]
        confidences = [float(conf) for _, text, conf in results if text]

        if not texts:
            return None, 0.0

        raw_text = " ".join(texts)
        if normalize_whitespace:
            raw_text = _normalize_whitespace(raw_text)

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        confidence = max(0.0, min(1.0, confidence))
        return raw_text, confidence

    def _parse_amount_from_text(
        self,
        text: str,
        *,
        allow_comma: bool,
        allow_dot: bool,
    ) -> Optional[float]:
        cleaned_text = _strip_currency_symbols(text)
        tokens = _extract_numeric_tokens(cleaned_text)

        for token in tokens:
            sanitized = token.replace(" ", "")
            if not sanitized:
                continue

            decimal_char: Optional[str] = None
            if "." in sanitized and "," in sanitized:
                # les deux présents → on considère le dernier comme séparateur décimal
                last_dot = sanitized.rfind(".")
                last_comma = sanitized.rfind(",")
                decimal_char = "." if last_dot > last_comma else ","
                other = "," if decimal_char == "." else "."
                sanitized = sanitized.replace(other, "")
            elif "," in sanitized:
                if not allow_comma:
                    continue
                decimal_char = ","
            elif "." in sanitized:
                if not allow_dot:
                    continue
                decimal_char = "."

            digits = sanitized.replace(".", "").replace(",", "")
            if decimal_char is not None:
                if decimal_char == "," and not allow_comma:
                    continue
                if decimal_char == "." and not allow_dot:
                    continue
                digits = sanitized.replace(decimal_char, ".")

            if not digits:
                continue
            if digits.count(".") > 1:
                continue
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", digits):
                continue

            return float(digits)

        return None

    def read_amount(
        self,
        patch: PatchType,
        *,
        allow_comma: bool = True,
        allow_dot: bool = True,
    ) -> tuple[Optional[float], float, str]:
        """Read a numeric amount from an image patch."""
        raw_text, confidence = self.read_text(patch, normalize_whitespace=False)
        if raw_text is None:
            return None, confidence, ""

        value = self._parse_amount_from_text(
            raw_text,
            allow_comma=allow_comma,
            allow_dot=allow_dot,
        )
        return value, confidence, raw_text


_GLOBAL_ENGINE: Optional[OcrEngine] = None


def get_engine(lang: str = "fr") -> OcrEngine:
    """Return a global singleton OcrEngine for the given language."""
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None or _GLOBAL_ENGINE.lang != lang:
        _GLOBAL_ENGINE = OcrEngine(lang=lang)
    return _GLOBAL_ENGINE


def read_text_from_patch(
    patch: PatchType,
    *,
    lang: str = "fr",
) -> tuple[Optional[str], float]:
    """Convenience wrapper around the global engine."""
    engine = get_engine(lang)
    return engine.read_text(patch)


def read_amount_from_patch(
    patch: PatchType,
    *,
    lang: str = "fr",
) -> tuple[Optional[float], float, str]:
    """Convenience wrapper for reading amounts from patches."""
    engine = get_engine(lang)
    return engine.read_amount(patch)

```
### objet/scanner/cards_recognition.py
```python
"""Card template helpers shared between scanner code and CLI tools."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
from PIL import Image

from objet.utils.pyauto import locate_in_image

__all__ = [
    "CardObservation",
    "TemplateIndex",
    "is_cover_me_cards",
    "is_card_present",
    "match_best",
    "recognize_card_observation",
    "recognize_number_and_suit",
    "trim_card_patch",
]

ROOT_TEMPLATE_SET = "__root__"


@dataclass
class CardObservation:
    """Observation brute d'une carte (issue de la capture)."""

    value: Optional[str]
    suit: Optional[str]
    value_score: float
    suit_score: float
    source: str = "capture"


class TemplateIndex:
    """Charge et organise les gabarits de cartes par *type de capture*."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.numbers: Dict[str, List[np.ndarray]] = {}
        self.suits: Dict[str, List[np.ndarray]] = {}
        self.numbers_by_set: Dict[str, Dict[str, List[np.ndarray]]] = {}
        self.suits_by_set: Dict[str, Dict[str, List[np.ndarray]]] = {}
        self.default_set: str = ROOT_TEMPLATE_SET

    @staticmethod
    def _prep(gray: np.ndarray) -> np.ndarray:
        return gray

    @staticmethod
    def _imread_gray(p: Path) -> Optional[np.ndarray]:
        try:
            img = Image.open(p).convert("L")
            return np.array(img)
        except Exception:
            return None

    def _load_dir(self, base: Path) -> Dict[str, List[np.ndarray]]:
        out: Dict[str, List[np.ndarray]] = {}
        if not base.exists():
            return out
        for label_dir in sorted(base.iterdir()):
            if not label_dir.is_dir():
                continue
            label = label_dir.name
            imgs: List[np.ndarray] = []
            for f in sorted(label_dir.glob("*.png")):
                g = self._imread_gray(f)
                if g is not None:
                    imgs.append(self._prep(g))
            if imgs:
                out[label] = imgs
        return out

    def load(self) -> None:
        """Charge les gabarits disponibles et détecte les ensembles déclarés."""

        self.numbers_by_set = {}
        self.suits_by_set = {}
        default: Optional[str] = None

        # 1) compat héritage : gabarits directement dans root/numbers|suits
        legacy_numbers = self._load_dir(self.root / "numbers")
        legacy_suits = self._load_dir(self.root / "suits")
        if legacy_numbers or legacy_suits:
            self.numbers_by_set[ROOT_TEMPLATE_SET] = legacy_numbers
            self.suits_by_set[ROOT_TEMPLATE_SET] = legacy_suits
            default = ROOT_TEMPLATE_SET

        # 2) Sous-dossiers (board/, hand/, ...)
        for subdir in sorted(self.root.iterdir()):
            if not subdir.is_dir():
                continue
            numbers = self._load_dir(subdir / "numbers")
            suits = self._load_dir(subdir / "suits")
            if not numbers and not suits:
                continue
            key = subdir.name
            self.numbers_by_set[key] = numbers
            self.suits_by_set[key] = suits
            if default is None and ROOT_TEMPLATE_SET not in self.numbers_by_set:
                default = key

        if default is None:
            # Aucun ensemble explicite → utiliser le premier trouvé ou root
            union_keys = list({*self.numbers_by_set.keys(), *self.suits_by_set.keys()})
            default = union_keys[0] if union_keys else ROOT_TEMPLATE_SET

        self.default_set = default
        self.numbers = self.numbers_by_set.get(default, {})
        self.suits = self.suits_by_set.get(default, {})

    def _normalise_set(self, template_set: Optional[str]) -> str:
        if template_set:
            return template_set
        return self.default_set

    def get_templates(
        self, template_set: Optional[str] = None
    ) -> Tuple[Dict[str, List[np.ndarray]], Dict[str, List[np.ndarray]]]:
        key = self._normalise_set(template_set)
        numbers = self.numbers_by_set.get(key, {})
        suits = self.suits_by_set.get(key, {})
        if not numbers and not suits and template_set:
            # Aucun template pour cet ensemble → fallback silencieux sur le défaut.
            key = self.default_set
            numbers = self.numbers_by_set.get(key, {})
            suits = self.suits_by_set.get(key, {})
        return numbers, suits

    def available_sets(self) -> List[str]:
        keys = { *self.numbers_by_set.keys(), *self.suits_by_set.keys() }
        return sorted(keys)

    def check_missing(
        self,
        expect_numbers: Optional[Iterable[str]] = None,
        expect_suits: Optional[Iterable[str]] = None,
        *,
        template_set: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        miss: Dict[str, List[str]] = {"numbers": [], "suits": []}
        numbers, suits = self.get_templates(template_set)
        if expect_numbers:
            for v in expect_numbers:
                if v not in numbers:
                    miss["numbers"].append(v)
        if expect_suits:
            for s in expect_suits:
                if s not in suits:
                    miss["suits"].append(s)
        return miss

    def missing_cards(
        self,
        expect_numbers: Iterable[str],
        expect_suits: Iterable[str],
        *,
        template_set: Optional[str] = None,
    ) -> List[str]:
        """Liste les combinaisons valeur/couleur impossibles faute de gabarits.

        Chaque carte attendue est décrite sous la forme ``<value>_of_<suit>`` et
        annotée avec la ou les références manquantes (valeur ou couleur).
        """

        numbers, suits = self.get_templates(template_set)
        numbers_available = set(numbers)
        suits_available = set(suits)
        missing: List[str] = []
        for value in expect_numbers:
            value_ok = value in numbers_available
            for suit in expect_suits:
                suit_ok = suit in suits_available
                if value_ok and suit_ok:
                    continue
                reasons: List[str] = []
                if not value_ok:
                    reasons.append(f"number '{value}'")
                if not suit_ok:
                    reasons.append(f"suit '{suit}'")
                reason_str = " and ".join(reasons)
                missing.append(f"{value}_of_{suit} (missing {reason_str})")
        return missing

    def append_template(
        self,
        template_set: Optional[str],
        label: str,
        img: Image.Image,
        *,
        is_number: bool,
    ) -> None:
        key = self._normalise_set(template_set)
        gray = np.array(img.convert("L"))
        arr = self._prep(gray)
        store_all = self.numbers_by_set if is_number else self.suits_by_set
        store = store_all.setdefault(key, {})
        store.setdefault(label, []).append(arr)
        if key == self.default_set:
            if is_number:
                self.numbers = store
            else:
                self.suits = store
        else:
            current_keys = { *self.numbers_by_set.keys(), *self.suits_by_set.keys() }
            if self.default_set not in current_keys:
                self.default_set = key
                self.numbers = self.numbers_by_set.get(self.default_set, {})
                self.suits = self.suits_by_set.get(self.default_set, {})


def _to_gray(img):
    """Normalise un patch en niveau de gris (ndarray 2D).

    Accepte :
    - un numpy.ndarray (BGR ou déjà en gris),
    - une image PIL,
    - au pire, tout objet convertible en ndarray.
    """
    # 1) Cas OpenCV / numpy
    if isinstance(img, np.ndarray):
        # Déjà en niveaux de gris
        if img.ndim == 2:
            return img
        # Image couleur (en pratique BGR si ça vient de cv2 / screen_crop)
        if img.ndim == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        raise ValueError(f"Format ndarray inattendu pour _to_gray: shape={img.shape}")

    # 2) Cas PIL.Image
    if isinstance(img, Image.Image):
        arr = np.array(img.convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # 3) Fallback : on tente de convertir en ndarray
    arr = np.array(img)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        # On part du principe que c’est du BGR (cas le plus probable avec OpenCV)
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

    raise ValueError(f"Type d'image non supporté pour _to_gray: {type(img)}")


def trim_card_patch(img: Image.Image | np.ndarray, border: int) -> Image.Image:
    """Retourne une version rognée du patch (toujours en PIL.Image)."""

    if border <= 0:
        if isinstance(img, Image.Image):
            return img
        if isinstance(img, np.ndarray):
            if img.ndim == 2:
                return Image.fromarray(img)
            return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return Image.fromarray(np.array(img))

    if isinstance(img, Image.Image):
        w, h = img.size
        if w <= border * 2 or h <= border * 2:
            return img
        return img.crop((border, border, w - border, h - border))

    arr = np.array(img)
    if arr.ndim not in (2, 3):
        return Image.fromarray(arr)

    h, w = arr.shape[:2]
    if w <= border * 2 or h <= border * 2:
        if arr.ndim == 2:
            return Image.fromarray(arr)
        return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))

    trimmed = arr[border : h - border, border : w - border]
    if arr.ndim == 2:
        return Image.fromarray(trimmed)
    return Image.fromarray(cv2.cvtColor(trimmed, cv2.COLOR_BGR2RGB))


def is_card_present(patch: np.ndarray | Image.Image, *, threshold: int = 240, min_ratio: float = 0.08) -> bool:
    """Heuristique simple : proportion de pixels *très clairs* sur la zone."""

    if isinstance(patch, np.ndarray):
        arr = patch
        if arr.ndim == 2:
            arr_u8 = arr.astype(np.uint8, copy=False)
            white = arr_u8 >= threshold
            ratio = float(white.mean())
            return ratio >= float(min_ratio)
        if arr.ndim == 3:
            arr_u8 = arr.astype(np.uint8, copy=False)
        else:
            raise ValueError(f"Unsupported array shape for card presence: {arr.shape}")
    elif isinstance(patch, Image.Image):
        arr_u8 = np.array(patch.convert("RGB"), dtype=np.uint8)
    else:
        raise TypeError(f"Unsupported patch type for card presence: {type(patch)!r}")

    if arr_u8.ndim == 2:
        white = arr_u8 >= threshold
    else:
        white = np.all(arr_u8 >= threshold, axis=2)

    ratio = float(white.mean())
    return ratio >= float(min_ratio)


def match_best(gray_img: np.ndarray, templates: List[np.ndarray], method: int = cv2.TM_CCOEFF_NORMED) -> float:
    best = -1.0
    for tpl in templates:
        if gray_img.shape[0] < tpl.shape[0] or gray_img.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(gray_img, tpl, method)
        _, score, _, _ = cv2.minMaxLoc(res)
        best = max(best, float(score))
    return best


def recognize_number_and_suit(
    number_patch: Image.Image,
    suit_patch: Image.Image,
    idx: TemplateIndex,
    *,
    template_set: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], float, float]:
    """Retourne (value, suit, score_value, score_suit)."""

    g_num = _to_gray(number_patch)
    g_suit = _to_gray(suit_patch)

    numbers, suits = idx.get_templates(template_set)

    best_num, best_num_score = None, -1.0
    for label, tpls in numbers.items():
        score = match_best(g_num, tpls)
        if score > best_num_score:
            best_num_score = score
            best_num = label

    best_suit, best_suit_score = None, -1.0
    for label, tpls in suits.items():
        score = match_best(g_suit, tpls)
        if score > best_suit_score:
            best_suit_score = score
            best_suit = label

    return best_num, best_suit, best_num_score, best_suit_score


def recognize_card_observation(
    number_patch: Image.Image | np.ndarray,
    suit_patch: Image.Image | np.ndarray,
    idx: TemplateIndex,
    *,
    template_set: Optional[str] = None,
    trim: int = 0,
) -> CardObservation:
    """Réalise une reconnaissance complète et retourne une observation structurée."""

    trimmed_num = trim_card_patch(number_patch, trim)
    trimmed_suit = trim_card_patch(suit_patch, trim)
    value, suit, value_score, suit_score = recognize_number_and_suit(
        trimmed_num,
        trimmed_suit,
        idx,
        template_set=template_set,
    )
    return CardObservation(value, suit, float(value_score), float(suit_score))





def _ensure_pil_image(region):
    """Accepte PIL.Image ou np.ndarray et renvoie toujours une PIL.Image."""
    if isinstance(region, Image.Image):
        return region

    if isinstance(region, np.ndarray):
        arr = region
        if arr.ndim == 2:
            # image grayscale
            return Image.fromarray(arr.astype("uint8"), mode="L")
        if arr.ndim == 3:
            # typiquement BGR venant de cv2 → on repasse en RGB
            if arr.shape[2] >= 3:
                rgb = arr[..., ::-1]  # BGR -> RGB
                return Image.fromarray(rgb.astype("uint8"), mode="RGB")
        raise ValueError(f"Unsupported numpy array shape for image: {arr.shape!r}")

    raise TypeError(f"Unsupported region type: {type(region)!r}")



import pyscreeze

ACTIONS_DIR = Path(__file__).resolve().parents[2] / "config" / "PMU"

ACTION_TEMPLATES: Dict[str, Path] = {
    
    "CHECK": ACTIONS_DIR / "check.png",
    "paid": ACTIONS_DIR / "paie.png",
    "RELANCER": ACTIONS_DIR / "relance.png",
    "fold": ACTIONS_DIR / "fold.png",
    "No_start": ACTIONS_DIR / "sit_out.png",
    "play": ACTIONS_DIR / "play.png",
    
}
 


@lru_cache(maxsize=len(ACTION_TEMPLATES)+1)
def _load_is_cover_me_cards_template(path) -> Optional[Image.Image]:
    """Load the reference template used to detect the FOLD overlay."""
    with Image.open(path) as img:
        return img.convert("RGB")


def is_cover_me_cards(region: Image.Image,threshold: float = 0.55,) -> bool:
    """Return ``True`` when the *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    region = _ensure_pil_image(region)
    haystack_rgb = region.convert("RGB")
    haystack_gray = cv2.cvtColor(np.array(haystack_rgb), cv2.COLOR_RGB2GRAY)
    ACTION_TEMPLATES.pop("paid", None)
    for path in ACTION_TEMPLATES.values():
        if is_cover(haystack_gray, path, threshold):
            return True
    return False

def is_etat_player(region: Image.Image,threshold: float = 0.55,) -> bool:
    """Return  *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    region = _ensure_pil_image(region)
    haystack_rgb = region.convert("RGB")
    haystack_gray = cv2.cvtColor(np.array(haystack_rgb), cv2.COLOR_RGB2GRAY)
    for action_name, path in ACTION_TEMPLATES.items():
        if is_cover(haystack_gray, path, threshold):
            return action_name
    return False
    
    
def is_cover(screen_array: np.ndarray, template_path: Path, threshold: float = 0.55,) -> bool:
    """Return ``True`` when the *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    haystack_rgb = cv2.cvtColor(screen_array, cv2.COLOR_BGR2RGB)
    haystack_gray = cv2.cvtColor(haystack_rgb, cv2.COLOR_RGB2GRAY)

    template_rgb = _load_is_cover_me_cards_template(template_path)
    template_gray = cv2.cvtColor(np.array(template_rgb), cv2.COLOR_RGB2GRAY)

    # matchTemplate → carte de scores normalisés
    res = cv2.matchTemplate(haystack_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)

    # max_val est la "confidence" [0, 1]
    if max_val >= threshold:
        return True
    return False
```
### objet/scanner/scan.py
```python

from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import ImageGrab, Image

from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
import pyautogui
from objet.utils.pyauto import locate_in_image
from objet.utils.calibration import bbox_from_region, load_coordinates
from objet.utils.logging_config import get_logger
from objet.scanner.cards_recognition import (
    TemplateIndex,
    is_cover_me_cards, is_etat_player,
    is_card_present,
    recognize_number_and_suit,is_cover
)
from objet.scanner.amount_ocr import OcrEngine

DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")
DEFAULT_ANCHOR_PATH = Path("config/PMU/anchor.png")
DEFAULT_CARDS_ROOT = Path("config/PMU/Cards")
DEFAULT_LOSE_PATH = Path("config/PMU/lose.png")


LOGGER = get_logger(__name__)


class ScanTable:
    """Scan de la table PMU basé sur capture écran + pyautogui.

    - Localisation de la fenêtre via un template d'ancre (me.png) avec locate_in_image().
    - ``screen_array`` conserve la capture plein écran en BGR (convention OpenCV).
    """
    #Todo fqire des objets scqn cqrds ... pour videe le fichier cards _recognition car bcp trop gros
    def __init__(self, *, value_threshold: float = 0.75, suit_threshold: float = 0.75) -> None:
        # --- Config / calibration ---
        self.coord_path = DEFAULT_COORD_PATH

        # Gabarit de référence (ancre) utilisé par pyautogui/locate
        self.reference_pil: Image.Image = Image.open(DEFAULT_ANCHOR_PATH).convert("RGB")

        # --- État runtime ---
        self.value_threshold = value_threshold
        self.suit_threshold = suit_threshold
        self.screen_array: Optional[np.ndarray] = None     # plein écran, BGR
        self.anchor_box: Optional[Tuple[int, int, int, int]] = None
        self.scan_string: str = "init"
        self.cards_root = DEFAULT_CARDS_ROOT
        self.template_index = TemplateIndex(self.cards_root)
        self.template_index.load()
        
        regions, _, _ = load_coordinates(self.coord_path)
        self.player_state_boxes = bbox_from_region(regions.get("player_state_me"))
        self.ocr =  OcrEngine()

        # Première capture
        self.screen_refresh()
        

        

    
    def test_scan(self) -> bool:
        self.screen_refresh()
        if self.is_lose():
            LOGGER.error("ARRET - ecran_perdu detecte=True")
            sys.exit("You lose")
        found = self.find_table()
        LOGGER.debug("SCAN test_table status=%s", found)
        return found
    
    def screen_refresh(self) -> None:
        """Capture plein écran dans self.screen_array (numpy BGR)."""
        grab = ImageGrab.grab()               # PIL RGB
        rgb = np.array(grab)                  # numpy RGB
        self.screen_array = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)  # numpy BGR
        self.anchor_box = None

    # ------------------------------------------------------------------
    # Localisation de la table via pyautogui
    # ------------------------------------------------------------------
    def find_table(self, *, grayscale: bool = True, confidence: float = 0.9) -> bool:
        """Localise la table via l'ancre.

        Met à jour :
          - ``self.anchor_box`` avec la bounding box de l'ancre (left, top, w, h)
          - ``self.scan_string`` : 'ok' ou "don't find".
        """
        if self.screen_array is None:
            self.scan_string = "no_screen"
            self.anchor_box = None
            LOGGER.warning("SKIP recherche_table raison=no_screen")
            return False

        # 1) Localiser l'ancre dans le plein écran via pyautogui
        try:
            box = locate_in_image(
                haystack=self.screen_array,
                needle=self.reference_pil,
                assume_bgr=True,
                grayscale=grayscale,
                confidence=confidence,
            )
        except pyautogui.ImageNotFoundException:
            self.scan_string = "don't find"
            self.anchor_box = None
            LOGGER.warning("SKIP recherche_table raison=anchor_introuvable confidence=%s", confidence)
            return False

        anchor_left, anchor_top, anchor_w, anchor_h = box
        self.anchor_box = (int(anchor_left), int(anchor_top), int(anchor_w), int(anchor_h))
        self.scan_string = "ok"
        LOGGER.debug("SCAN table anchor=%s", self.anchor_box)
        return True

    # ------------------------------------------------------------------
    # Scan des cartes directement sur la capture plein écran
    # ------------------------------------------------------------------

    def scan_carte(
        self,
        position_value: Tuple[int, int, int, int],
        position_suit: Tuple[int, int, int, int],
        *,
        template_set: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], float, float]:
        """
        Retourne:
            (value, suit, confidence_value, confidence_suit)

        - value, suit : str ou None
        - confidence_* : float entre 0.0 et 1.0
        """
        # crops séparés pour la valeur et le symbole
        image_card_value = self._extract_patch(position_value)
        image_card_suit = self._extract_patch(position_suit)


        if template_set == "hand" and self._should_skip_for_fold(image_card_value):
            LOGGER.debug("SCAN carte skip raison=cover_main template_set=%s", template_set)
            return None, None, 0.0, 0.0

        if is_card_present(image_card_value):
            carte_value, carte_suit, score_value, score_suit = recognize_number_and_suit(
                image_card_value,
                image_card_suit,
                self.template_index,
                template_set=template_set,
            )

            conf_val = float(max(0.0, score_value or 0.0))
            conf_suit = float(max(0.0, score_suit or 0.0))

            value_ok = carte_value if (carte_value and conf_val >= self.value_threshold) else None
            suit_ok = carte_suit if (carte_suit and conf_suit >= self.suit_threshold) else None

            LOGGER.debug(
                "SCAN carte brut template_set=%s value=%s suit=%s score_value=%.3f score_suit=%.3f accepted_value=%s accepted_suit=%s",
                template_set,
                carte_value,
                carte_suit,
                conf_val,
                conf_suit,
                value_ok,
                suit_ok,
            )

            return value_ok, suit_ok, conf_val, conf_suit
        LOGGER.debug("SCAN carte vide template_set=%s", template_set)
        return None, None, 0.0, 0.0



    def _should_skip_for_fold(self,number_patch: np.ndarray) -> bool:
        state_patch = self._extract_patch(self.player_state_boxes, pad=0)
        return  is_cover_me_cards(state_patch, threshold=0.6)
        
       


    def scan_player(self, position_money,position_etat):
        etat = is_etat_player(self._extract_patch(position_etat))
        value = self.scan_money( position_money)       
        return etat, value

    def scan_money(self, position) -> Optional[float]:
        img = self._extract_patch(position)
        value, confidence, raw_text = self.ocr.read_amount(img)
        LOGGER.debug(
            "SCAN ocr_amount raw=%r confidence=%.3f value=%s",
            raw_text,
            confidence,
            value,
        )
        return None if value is None else value


    def scan_bouton(self, position):
        img = self._extract_patch(position)
        texte, confidence = self.ocr.read_text(img)
        LOGGER.debug("SCAN ocr_button raw=%r confidence=%.3f", texte, confidence)
        return texte if texte else None


    def is_lose(self) -> bool:
        return is_cover(self.screen_array, DEFAULT_LOSE_PATH)
        
        
        
        
    def _extract_patch(self, box: Tuple[int, int, int, int], pad: int = 3) -> np.ndarray:
        """Retourne un crop (numpy BGR) pour ``box=(x,y,w,h)`` avec padding et clamp."""

        if self.screen_array is None:
            return np.empty((0, 0), dtype=np.uint8)

        x, y, w, h = box
        x = int(round(x))
        y = int(round(y))
        w = max(0, int(round(w)))
        h = max(0, int(round(h)))

        if w == 0 or h == 0:
            return np.empty((0, 0), dtype=np.uint8)

        x0 = max(0, int(x - pad))
        y0 = max(0, int(y - pad))

        h_scr, w_scr = self.screen_array.shape[:2]
        x1 = min(w_scr, int(x + w + pad))
        y1 = min(h_scr, int(y + h + pad))

        if x1 <= x0 or y1 <= y0:
            return np.empty((0, 0), dtype=np.uint8)

        img = self.screen_array[y0:y1, x0:x1].copy()
        return img

if __name__ == "__main__":
    scan = ScanTable()
    print(scan.test_scan())
    

    import cv2
    import numpy as np
    from PIL import Image

    img = scan.screen_array  # BGR

    if isinstance(img, np.ndarray):
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).show()
    elif isinstance(img, Image.Image):
        img.show()
    else:
        print("Type d'image inattendu:", type(img))
        

```
### objet/services/__init__.py
```python
"""Services d'orchestration et composants applicatifs.

Les imports sont différés pour éviter de charger les dépendances écran/OCR
quand un seul service léger est demandé.
"""

__all__ = [
    "Controller",
    "Table",
]


def __getattr__(name: str):
    if name == "Controller":
        from .controller import Controller

        return Controller
    if name == "Table":
        from .table import Table

        return Table
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)

```
### objet/services/card_identifier.py
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
card_identifier.py — service d’identification incrémentale des cartes.

- Utilise le dataset `config/<game>/cards/` via TemplateIndex.
- Tente une reco par gabarits.
- Si les deux (valeur + couleur) sont fiables (>= strict) → retour direct, sans UI.
- Sinon, si interactive=True :
    * ouvre un mini-dialog Tk/CustomTkinter,
    * ne demande QUE la partie inconnue (valeur OU couleur),
    * enregistre les patches rognés sous `cards/`,
    * met à jour l’index dans la foulée (effet immédiat sur les cartes suivantes).

API principale :
    CardIdentifier.identify_from_patches(...)
    CardIdentifier.identify_from_table(...)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple
import itertools
import time
import sys

# ajoute le VRAI project root: .../aide_decission
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from objet.scanner.cards_recognition import (
    ROOT_TEMPLATE_SET,
    TemplateIndex,
    is_cover_me_cards,
    is_card_present,
    recognize_card_observation,
    trim_card_patch,
)

# Si dans ton projet CardPatch/collect_card_patches viennent de _utils, adapte ce import :
from scripts._utils import CardPatch, collect_card_patches  # ajuste si besoin

DEFAULT_NUMBERS: Sequence[str] = (
    "?",
    "A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2",
)
DEFAULT_SUITS: Sequence[str] = ("?", "spades", "hearts", "diamonds", "clubs")


def _trim(img: Image.Image, border: int) -> Image.Image:
    return trim_card_patch(img, border)


def _make_preview(num_img: Image.Image, suit_img: Image.Image) -> Image.Image:
    """Empile number/suit verticalement pour l’UI."""
    num_w, num_h = num_img.size
    suit_w, suit_h = suit_img.size
    width = max(num_w, suit_w)
    spacer = 6
    preview = Image.new("RGB", (width, num_h + suit_h + spacer), "#f0f0f0")
    preview.paste(num_img, ((width - num_w) // 2, 0))
    preview.paste(suit_img, ((width - suit_w) // 2, num_h + spacer))
    return preview


@dataclass
class IdentifyResult:
    number: str
    suit: str
    meta: Dict[str, object]


class _SingleCardDialog:
    """
    Boîte de dialogue minimale pour compléter uniquement la partie inconnue.

    - missing_number / missing_suit contrôlent quels champs sont affichés.
    - suggested_* servent de valeur pré-sélectionnée dans les menus.
    """

    def __init__(
        self,
        number_img: Image.Image,
        suit_img: Image.Image,
        *,
        missing_number: bool,
        missing_suit: bool,
        number_choices: Sequence[str],
        suit_choices: Sequence[str],
        suggested_number: Optional[str] = None,
        suggested_suit: Optional[str] = None,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Identifier la carte")
        self.root.geometry("560x480")

        # action: "ok" | "cancel" | "delete"
        self.action: str = "cancel"
        self.result: Optional[Tuple[str, str]] = None

        # Valeurs par défaut (y compris si le champ n’est pas affiché)
        self.number_var = tk.StringVar(
            value=(suggested_number or (number_choices[0] if number_choices else "?"))
        )
        self.suit_var = tk.StringVar(
            value=(suggested_suit or (suit_choices[0] if suit_choices else "?"))
        )

        top = ctk.CTkFrame(self.root)
        top.pack(fill="both", expand=True, padx=12, pady=12)

        preview = _make_preview(number_img, suit_img)
        self.photo = ImageTk.PhotoImage(preview)
        self.img_lbl = ctk.CTkLabel(top, image=self.photo, text="", compound="top")
        self.img_lbl.pack(pady=8)

        form = ctk.CTkFrame(top)
        form.pack(pady=8)

        row = 0
        if missing_number:
            ctk.CTkLabel(form, text="Valeur").grid(row=row, column=0, padx=8, pady=6)
            self.num_menu = ctk.CTkOptionMenu(
                form,
                values=list(number_choices) or ["?"],
                variable=self.number_var,
            )
            self.num_menu.grid(row=row, column=1, padx=8, pady=6)
            row += 1
        if missing_suit:
            ctk.CTkLabel(form, text="Couleur").grid(row=row, column=0, padx=8, pady=6)
            self.suit_menu = ctk.CTkOptionMenu(
                form,
                values=list(suit_choices) or ["?"],
                variable=self.suit_var,
            )
            self.suit_menu.grid(row=row, column=1, padx=8, pady=6)
            row += 1

        btns = ctk.CTkFrame(top)
        btns.pack(pady=10)

        ctk.CTkButton(btns, text="Valider", command=self._on_save).pack(
            side="left", padx=8
        )
        ctk.CTkButton(btns, text="Annuler", command=self._on_cancel).pack(
            side="left", padx=8
        )
        # Nouveau bouton Delete
        ctk.CTkButton(btns, text="Delete", command=self._on_delete).pack(
            side="left", padx=8
        )

    def run(self) -> Optional[Tuple[str, str]]:
        self.root.mainloop()
        return self.result

    def _on_save(self) -> None:
        self.action = "ok"
        self.result = (
            self.number_var.get().strip() or "?",
            self.suit_var.get().strip() or "?",
        )
        self.root.destroy()

    def _on_cancel(self) -> None:
        self.action = "cancel"
        self.result = None
        self.root.destroy()

    def _on_delete(self) -> None:
        # signale qu’on veut supprimer la capture
        self.action = "delete"
        self.result = None
        self.root.destroy()


class CardIdentifier:
    """
    Service réutilisable d’identification incrémentale (par patches ou par table).

    - threshold : score à partir duquel on considère que la valeur/couleur est "connue"
                  (on ne la redemande pas à l’utilisateur).
    - strict    : score à partir duquel on autoskip complètement la carte
                  (pas d’UI si les deux >= strict).
    """

    def __init__(
        self,
        game_dir: Path | str,
        *,
        trim: int = 6,
        threshold: float = 0.92,
        strict: float = 0.985,
        number_choices: Sequence[str] = DEFAULT_NUMBERS,
        suit_choices: Sequence[str] = DEFAULT_SUITS,
    ) -> None:
        self.game_dir = Path(game_dir)
        self.cards_root = self.game_dir / "cards"
        self.trim = int(trim)
        self.threshold = float(threshold)
        self.strict = float(strict)

        self.number_choices = list(number_choices)
        self.suit_choices = list(suit_choices)

        self.idx = TemplateIndex(self.cards_root)
        self.idx.load()

        self._counter = itertools.count(1)
        self._last_template_set: Optional[str] = None

    # ---------- helpers internes ----------

    def _normalise_template_set(self, template_set: Optional[str]) -> Optional[str]:
        """Choisit un set de templates cohérent quand le patch n’en indique pas."""
        if template_set:
            return template_set
        if self._last_template_set:
            return self._last_template_set
        default = self.idx.default_set
        return None if default == ROOT_TEMPLATE_SET else default

    def _save_if_missing(
        self,
        num_img: Image.Image,
        suit_img: Image.Image,
        number_label: str,
        suit_label: str,
        save_number: bool,
        save_suit: bool,
        base_key: str,
        template_set: Optional[str],
    ) -> None:
        ts = int(time.time())
        idx = next(self._counter)
        base = f"{base_key}_{ts}_{idx:04d}"

        resolved_set = self._normalise_template_set(template_set)
        self._last_template_set = resolved_set

        if resolved_set:
            root = self.cards_root / resolved_set
        else:
            root = self.cards_root

        if save_number:
            p = root / "numbers" / number_label / f"{base}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            num_img.save(p)
        if save_suit:
            p = root / "suits" / suit_label / f"{base}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            suit_img.save(p)

    def _update_index(
        self,
        label: str,
        img: Image.Image,
        *,
        is_number: bool,
        template_set: Optional[str],
    ) -> None:
        resolved_set = self._normalise_template_set(template_set)
        self.idx.append_template(resolved_set, label, img, is_number=is_number)

    # ---------- API patches ----------

    def identify_from_patches(
        self,
        number_patch: Image.Image,
        suit_patch: Image.Image,
        *,
        base_key: str = "live",
        template_set: Optional[str] = None,
        interactive: bool = True,
        force_all: bool = False,
    ) -> IdentifyResult:
        # 1) Trim + reco
        tpl_set = self._normalise_template_set(template_set)

        observation = recognize_card_observation(
            number_patch,
            suit_patch,
            self.idx,
            template_set=tpl_set,
            trim=self.trim,
        )

        num_s = observation.value
        suit_s = observation.suit
        score_num = float(observation.value_score)
        score_suit = float(observation.suit_score)

        # Niveaux de confiance
        num_known = bool(num_s) and score_num >= self.threshold
        suit_known = bool(suit_s) and score_suit >= self.threshold
        num_strict = bool(num_s) and score_num >= self.strict
        suit_strict = bool(suit_s) and score_suit >= self.strict

        # 1.a Autoskip "dur" : on est très sûr sur les deux
        if num_strict and suit_strict and not force_all:
            return IdentifyResult(
                num_s,
                suit_s,
                {
                    "source": "auto",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        trimmed_number = _trim(number_patch, self.trim)
        trimmed_suit = _trim(suit_patch, self.trim)

        # Partie manquante = en-dessous du seuil "connue" (ou si force_all)
        missing_number = (not num_known) or force_all
        missing_suit = (not suit_known) or force_all

        # 1.b Mode non interactif → on ne montre jamais d'UI
        if not interactive:
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "guess",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        # 1.c IMPORTANT : si rien à demander → surtout ne pas ouvrir de popup vide
        if not (missing_number or missing_suit):
            # "auto-soft" : on fait confiance au modèle, même si ce n'est pas >= strict
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "auto-soft",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        # 2) Ici on a vraiment quelque chose à compléter → on ouvre une mini-UI
        dialog = _SingleCardDialog(
            trimmed_number,
            trimmed_suit,
            missing_number=missing_number,
            missing_suit=missing_suit,
            number_choices=self.number_choices,
            suit_choices=self.suit_choices,
            suggested_number=num_s,
            suggested_suit=suit_s,
        )
        out = dialog.run()
        action = dialog.action  # "ok" | "cancel" | "delete"

        # 2.a Delete → laisse identify_card.py gérer la suppression physique
        if action == "delete":
            return IdentifyResult(
                "?", "?",
                {
                    "source": "delete",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        if out is None:
            # Annulé → renvoyer la meilleure info disponible
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "cancel",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        lab_num, lab_suit = out

        save_number = missing_number and lab_num not in {"", "?"}
        save_suit = missing_suit and lab_suit not in {"", "?"}

        # 3) Sauvegarde + MAJ index en temps réel
        if save_number or save_suit:
            self._save_if_missing(
                trimmed_number,
                trimmed_suit,
                lab_num,
                lab_suit,
                save_number,
                save_suit,
                base_key,
                tpl_set,
            )
            if save_number:
                self._update_index(
                    lab_num,
                    trimmed_number,
                    is_number=True,
                    template_set=tpl_set,
                )
            if save_suit:
                self._update_index(
                    lab_suit,
                    trimmed_suit,
                    is_number=False,
                    template_set=tpl_set,
                )

        final_num = lab_num or (num_s if num_s else "?")
        final_suit = lab_suit or (suit_s if suit_s else "?")

        return IdentifyResult(
            final_num,
            final_suit,
            {
                "source": "labeled",
                "score_number": score_num,
                "score_suit": score_suit,
            },
        )

    # ---------- API pratique par image de table ----------

    def identify_from_table(
        self,
        table_img: Image.Image,
        regions: Dict[str, object],
        base_key: str,
        *,
        interactive: bool = True,
        force_all: bool = False,
    ) -> IdentifyResult:
        pairs = collect_card_patches(table_img.convert("RGB"), regions, pad=0)
        card_patch = pairs.get(base_key)
        if not card_patch:
            return IdentifyResult("?", "?", {"source": "error", "reason": "region-missing"})

        tpl_set = card_patch.template_set

        # Overlay HOLD / FOLD → on considère la carte vide
        tpl_lower = (tpl_set or "").lower()
        if "hand" in tpl_lower and is_cover_me_cards(card_patch.number):
            return IdentifyResult("?", "?", {"source": "empty", "reason": "hold-overlay"})

        # Test présence carte
        if not is_card_present(card_patch.number, threshold=215, min_ratio=0.04):
            return IdentifyResult("?", "?", {"source": "empty", "reason": "no-card"})

        return self.identify_from_patches(
            card_patch.number,
            card_patch.suit,
            base_key=base_key,
            template_set=tpl_set,
            interactive=interactive,
            force_all=force_all,
        )

```
### objet/services/controller.py
```python
# launch_controller.py à la racine du projet

from pathlib import Path
import sys
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.logging_config import get_logger


LOGGER = get_logger(__name__)


class Controller:
    def __init__(self):
        self.count = 0
        self.running = False
        self.cpt = 0
        self.game_stat = {}
        from objet.services.decision import Decision
        from objet.services.game import Game
        self.game = Game()
        self.decision = Decision()

    def main(self):
        self.count += 1
        LOGGER.info("debut cycle_controller count=%s", self.count)
        if self.game.scan_to_data_table():
            new_party = self.game.update_from_scan()
            result = self.game_stat_to_string(new_party)
            if new_party:
                self.game.ack_new_party()
            LOGGER.info(
                "fin cycle_controller count=%s status=ok nouvelle_partie=%s",
                self.count,
                bool(new_party),
            )
            return result
        self.cpt += 1
        LOGGER.warning("SKIP table_introuvable count=%s scan_echec=%s", self.count, self.cpt)
        return f"don t find     Scan n°{self.cpt}"
        

    
    def game_stat_to_string(self, new_party_state: Optional[bool] = None):
        """
        Formate les informations du jeu pour l'utilisateur.

        Returns:
            str: Une chaîne de caractères contenant les informations formatées.
        """
        # Récupération des informations de base
        
        # Fonction pour arrondir à 4 chiffres significatifs
        def round_sig(x, sig=4):
            if isinstance(x, (int, float)):
                return float(f"{x:.{sig}g}")
            else:
                return x

        # Arrondi des valeurs numériques
        pot = round_sig(self.game.etat.pot)

        chance_win_0 = round_sig(self.game.etat.chance_win_0)
        Call_max = round_sig(self.game.etat.Call_max)
        ev =  round_sig(self.game.etat.ev)
        decision_result = self.decision.decide(self.game)
        decision_line = f"Action: {decision_result.action} (raison: {decision_result.reason})"
        if decision_result.raise_amount is not None:
            decision_line += f" | Raise: {round_sig(decision_result.raise_amount)}"

        # Informations sur les cartes du joueur
        me_cards_str = [card.formatted for card in self.game.table.cards.me_cards()]
        

        # Informations sur le board
        board_cards_str = [card.formatted for card in self.game.table.cards.board_cards()]
        
        player_scan = [i for i in[f"J{i+1} "+( "🟢" if player.is_activate() else "⚪")+f" : {player.fond} "
                    for i, player in enumerate(self.game.table.players)]]

        # Informations sur les boutons
        # buttons_info = []
        # # Ajout d'une ligne d'en-tête avec des largeurs de colonnes fixes
        # buttons_info.append(f"{'Bouton':<10} {'Action':<15} {'Valeur':<10} {'Gain':<10}")
        # buttons_info.append('-' * 50)  # Ligne de séparation

        # for i in range(1, 4):
        #     button = self.game.table.buttons.buttons.get(f'button_{i}')
        #     if button:
        #         name = button.name if button.name is not None else ''
        #         value = round_sig(button.value) if button.value is not None else ''
        #         gain = round_sig(button.gain) if button.gain is not None else ''
        #         buttons_info.append(f"{f'Button {i}':<10} {name:<15} {str(value):<10} {str(gain):<10}")
        #     else:
        #         buttons_info.append(f"{f'Button {i}':<10} {'':<15} {'':<10} {'':<10}")

        # buttons_str = '\n'.join(buttons_info)

        # Informations sur l'argent des joueurs
        # player_money = metrics.player_money
        # player_money_info = []
        # for player, money in player_money.items():
        #     money_str = str(round_sig(money)) if money is not None else 'Absent'
        #     player_money_info.append(f"{player}: {money_str}")

        # player_money_str = '\n'.join(player_money_info)
        etat_me_cards_str = [card.formatted for card in self.game.etat.cards.me_cards()]
        etat_board_cards_str = [card.formatted for card in self.game.etat.cards.board_cards()]
        etat_nbr_player = f"Player start {self.game.etat.players.nbr_player_start}    Player active {self.game.etat.players.nbr_player_active}"

        new_party_notice = ""
        if new_party_state is True:
            new_party_notice = "Nouvelle partie détectée (pot en baisse)."
        elif new_party_state is None:
            new_party_notice = "Pot non détecté, impossible de statuer sur la nouvelle partie."
        
        metrics_lines = [
            f"Pot: {pot}",
            f"Chance win (1): {chance_win_0}",
            f"Ev: {ev}",
            f"Call_max: {Call_max}",
        ]
        metrics_str = " | ".join(metrics_lines)
        
        Bouton_l = [
            
            f"B{i} {b.etat} :{b.value}" if b.value !=0 else f"B{i} {b.etat}" if b.enabled else ""
            for i ,b in enumerate(self.game.table.buttons)
        ]
        Bouton_l = "  |  ".join(Bouton_l)



        return (
        #     f"Nombre de joueurs: {nbr_player}   Pot: {pot} €   Fond: {fond} €\n"
            
            f"Mes cartes: {me_cards_str}\n"
            f"Cartes sur le board: {board_cards_str}\n"
            f"{player_scan}\n"
            
            
            f"{'=' * 30}ETAT{'=' * 30}\n"
            f"Mes cartes: {etat_me_cards_str}\n"
            f"Cartes sur le board: {etat_board_cards_str}\n"
            f"{etat_nbr_player}\n"
            f"{'=' * 30}Métriques{'=' * 30}\n"
            f" {metrics_str}\n"
            f" {Bouton_l}\n"
            f"Decision -> {decision_line}\n"
        #     f"Chance de gagner (1 joueur): {chance_win_0}\n"
        #     f"Chance de gagner ({nbr_player} joueurs): {chance_win_x}\n\n"
        #     f"Informations sur les boutons:\n{buttons_str}\n\n"
        #     f"Argent des joueurs:\n{player_money_str}"
         )




if __name__ == "__main__":
    controller = Controller()
    result = controller.main()
    print(result)



```
### objet/services/decision.py
```python
"""Decision helper to recommend a poker action for the hero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from objet.entities.card import Card, CardsState
from objet.services.game import Game
from objet.utils.logging_config import get_logger

ActionType = Literal["WAIT", "FOLD", "CALL", "CHECK", "RAISE"]
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class DecisionResult:
    """Immutable result describing the recommended poker action."""

    action: ActionType
    reason: str
    raise_amount: Optional[float] = None


class Decision:
    """Simple, fail-fast decision engine for the hero."""

    FOLD_THRESHOLD: float = 0.01

    def decide(self, game: Game) -> DecisionResult:
        """Return the recommended action for the hero based on the current state."""
        if getattr(game, "new_party_detected", False):
            return _log_decision(DecisionResult(action="WAIT", reason="new_party_pending_reset"))

        if not game.etat.cards.is_ready_for_cal():
            return _log_decision(DecisionResult(action="WAIT", reason="hero_cards_not_detected_yet"))

        buttons = getattr(game.table, "buttons", None)
        if buttons is None or not buttons.one_is_activate():
            return _log_decision(DecisionResult(action="WAIT", reason="not_buttons"))

        min_value = buttons.min_value()
        Call_max = game.etat.Call_max
        LOGGER.debug("DECISION contexte call_max=%s min_value=%s", Call_max, min_value)

        if Call_max < min_value - self.FOLD_THRESHOLD:
            return _log_decision(DecisionResult(action="CHECK", reason="chance_win_below_fold_threshold"))

        if Call_max > min_value + self.FOLD_THRESHOLD * 5 :
            return _log_decision(DecisionResult(action="RAISE", reason="chance_win_between_thresholds"))
        
    
        return _log_decision(
            DecisionResult(
                action="CALL",
                reason="chance_win_above_aggressive_threshold",
                # raise_amount=raise_amount,
            )
        )

 





def _log_decision(result: DecisionResult) -> DecisionResult:
    LOGGER.info("DECISION action=%s reason=%s raise=%s", result.action, result.reason, result.raise_amount)
    return result


__all__ = ["ActionType", "DecisionResult", "Decision"]

```
### objet/services/game.py
```python
"""Gestion centralisée de l'état du jeu."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.entities.card import Card, CardsState
from objet.entities.player import Players
from objet.entities.buttons import Buttons

from objet.services.table import Table
from objet.scanner.cards_recognition import CardObservation
from objet.utils.capture import CaptureState
from objet.utils.logging_config import get_logger

from pokereval.hand_evaluator import HandEvaluator

from objet.services.script_state import SCRIPT_STATE_USAGE, StatePortion

LOGGER = get_logger(__name__)

GAME_STREET_ORDER = {
    "IDLE": 0,
    "PREFLOP": 1,
    "FLOP": 2,
    "TURN": 3,
    "RIVER": 4,
}

GAME_STREET_BY_BOARD_COUNT = {
    0: "PREFLOP",
    3: "FLOP",
    4: "TURN",
    5: "RIVER",
}

GAME_VISIBLE_CARD_COUNT = {
    "IDLE": 0,
    "PREFLOP": 2,
    "FLOP": 5,
    "TURN": 6,
    "RIVER": 7,
}



@dataclass
class Etat:
    """Stocke l'état courant de la table et calcule les décisions."""
    cards: CardsState = field(default_factory=CardsState)
    players: Players = field(default_factory=Players)
    chance_win_0: Optional[float] = None
    pot: Optional[float] = None
    montant_a_jouer: float = None
    cards_change : int = 0
    ev : float = 0
    Call_max : float = 0

    def __post_init__(self) -> None:
        """Garantit que les états dépendants existent."""
        self.cards = CardsState()
        self.players = Players()

    
    
   

    def _cal_win_chances(self) -> float:
        """Calcule les chances de gain en fonction des cartes connues."""

        me_cards = self.cards.me_cards()

        hero_cards = [
            card.poker_card
            for idx, card in enumerate(me_cards)
        ]

        board_cards = [card for card in self.cards.board_cards() if card.formatted]
        board_length = len(board_cards)
        if board_length not in (0, 3, 4, 5):
            raise ValueError("Le nombre de cartes sur le board est incorrect.")

        board_poker_cards = [
            card.poker_card
            for idx, card in enumerate(board_cards)
        ]
        chance_win_0 = HandEvaluator.evaluate_hand(hero_cards, board_poker_cards)
        self.chance_win_0 = chance_win_0
        
        self.chance_win = chance_win_0**(self.players.nbr_player_start -1 )
        LOGGER.debug(
            "CALCUL chance_win hero=%s board=%s joueurs=%s chance_1=%s chance_table=%s",
            [card.formatted for card in me_cards],
            [card.formatted for card in board_cards],
            self.players.nbr_player_start,
            self.chance_win_0,
            self.chance_win,
        )
        
        return chance_win_0


    def _cal_EV(self,to_call = 0.02)-> float:
        P = self.chance_win
        Pot = self.pot                # pot avant ton call
        C = to_call                   # montant à payer maintenant
        return P * (Pot + C) - C
        

    def _cal_max_call(self) -> None:
        P = self.chance_win
        Pot = self.pot
        self.Call_max = (P * Pot) / (1.0 - P)
        # >0: call OK, <0: fold

    
    def _cal(self):
        if self.cards.is_ready_for_cal():
            self._cal_win_chances()
            self.ev = self._cal_EV()
            self._cal_max_call()
            self._calcul_montant_a_jouer()
            LOGGER.info(
                "CALCUL etat pot=%s chance=%s ev=%s call_max=%s montant=%s",
                self.pot,
                self.chance_win_0,
                self.ev,
                self.Call_max,
                self.montant_a_jouer,
            )
        else:
            LOGGER.debug("SKIP calcul raison=cartes_hero_incompletes")
    
    
    def _calcul_montant_a_jouer(self) -> float:

        denominateur = 1 - (self.chance_win_0 * (self.players.nbr_player_start + 1))

        self.montant_a_jouer = (self.chance_win_0* self.pot) / denominateur
        return self.montant_a_jouer
    
    
    
    
    
    def update_players(self, players: Players) -> None:
        self.players = players
        self.players.cal_nbr_player_start()
        self.players.cal_nbr_player_active()


    def update_cards_state(self, cards_state: CardsState) -> None:
        """Met à jour l'état des cartes."""
        nbr_scan = 3 *2
        for i,card in enumerate(cards_state.board):
            if self.cards.board[i].formatted is None:
                self.cards.board[i] = card
            if card.formatted is None :
                continue   
            if card.formatted != self.cards.board[i].formatted:
                self.cards_change +=2
                if self.cards_change >= nbr_scan:
                        self.cards.board[i] = card
                        self.cards_change = 0
        
            
        for i,card in enumerate(cards_state.me):
            if self.cards.me[i].formatted is None:
                self.cards.me[i] = card
            if card.formatted is None :
                continue   
            if card.formatted != self.cards.me[i].formatted:
                self.cards_change +=2
                if self.cards_change >= nbr_scan:
                        self.cards.me[i] = card
                        self.cards_change = 0
        self.cards_change -=1

    def update(self, *, cards_state: CardsState, players: Players, pot: Optional[float]) -> None:
        self.update_cards_state(cards_state)
        self.update_players(players)
        self.pot = pot if pot else self.pot
        self._cal()


@dataclass
class Game:
    """Stocke l'état courant de la table et calcule les décisions."""

    etat: Etat = field(default_factory=Etat)
    table: Table = field(default_factory=Table)
    resultat_calcul: Dict[str, Any] = field(default_factory=dict)
    street: str = "IDLE"
    workflow: Optional[str] = None
    pot_drop_tolerance: float = 0.01
    _last_pot_amount: Optional[float] = field(default=None, init=False, repr=False)
    _new_party_flag: bool = field(default=False, init=False, repr=False)
    _pending_new_party_cleanup: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Garantit que les états dépendants existent."""
        self.table.cards = CardsState()
        self.table.buttons = Buttons()
        self.table.captures = CaptureState()
        



    
    @property
    def cards(self) -> CardsState:
        return self.table.cards

    @cards.setter
    def cards(self, state: CardsState) -> None:
        self.table.cards = state

   
    def scan_to_data_table(self) -> bool:
        LOGGER.info("debut workflow_scan street=%s", self.street)
        if not self.table.launch_scan():
            LOGGER.warning("fin workflow_scan status=skip raison=table_introuvable")
            return False
        LOGGER.info("fin workflow_scan status=ok street=%s", self.street)
       
        return True
    

    def update_from_scan(self) -> Optional[bool]:
        """Met à jour l'état du jeu à partir du dernier scan.

        Returns:
            Optional[bool]: True si une nouvelle partie a été détectée, False sinon, None si le pot n'a pas été lu.
        """

        LOGGER.info(
            "debut update_game street=%s pot=%s",
            self.street,
            getattr(self.table.pot, "amount", None),
        )

        party_state = self._detect_new_party()
        if party_state is True:
            LOGGER.info("fin update_game status=nouvelle_partie")
            return True

        self.etat.update(
            cards_state=self.table.cards,
            players=self.table.players,
            pot=getattr(self.table.pot, "amount", None),
        )
        LOGGER.info("fin update_game status=ok nouvelle_partie=%s", party_state)
        return party_state


   



    # ---- Décision ----------------------------------------------------
    def decision(self) -> Optional[str]:
        raise ValueError("Aucune logique de décision directe dans Game.decision.")

    # ---- Calculs internes --------------------------------------------
    def _detect_new_party(self) -> Optional[bool]:
        # Le scan peut rater une carte ou lire un pot trop bas une seule fois.
        # Une nouvelle main est donc validee seulement si le pot baisse ET si
        # le nombre de cartes visibles baisse aussi. Exception: en PREFLOP, une
        # nouvelle main peut encore avoir 2 cartes visibles, donc la baisse du
        # pot suffit si le scan indique toujours un PREFLOP coherent.
        if self._pending_new_party_cleanup:
            self._new_party_flag = True
            LOGGER.debug("NOUVELLE_PARTIE pending_cleanup=True")
            return True

        observed_street = self._observed_street()
        observed_card_count = self._observed_card_count()
        current_pot = getattr(self.table.pot, "amount", None)
        if current_pot is None:
            self._accept_observed_street(observed_street)
            LOGGER.warning("SKIP pot_absent street=%s observed=%s", self.street, observed_street)
            return None

        if self._last_pot_amount is None:
            self._last_pot_amount = current_pot
            self._new_party_flag = False
            self._accept_observed_street(observed_street)
            LOGGER.debug("INIT pot amount=%s street=%s", current_pot, self.street)
            return False

        pot_dropped = current_pot < self._last_pot_amount - self.pot_drop_tolerance
        if pot_dropped:
            if observed_street in (None, "IDLE"):
                self._new_party_flag = False
                LOGGER.warning(
                    "SKIP baisse_pot_scan_incoherent pot=%s->%s cards=%s street=%s observed=%s",
                    self._last_pot_amount,
                    current_pot,
                    observed_card_count,
                    self.street,
                    observed_street,
                )
                return False

            current_card_count = GAME_VISIBLE_CARD_COUNT.get(self.street, 0)
            cards_reduced = observed_card_count < current_card_count
            same_preflop = self.street == "PREFLOP" and observed_street == "PREFLOP"

            if cards_reduced or same_preflop:
                previous_pot = self._last_pot_amount
                self._new_party_flag = True
                self._pending_new_party_cleanup = True
                self._last_pot_amount = current_pot
                if observed_street is not None:
                    self.street = observed_street
                LOGGER.info(
                    "NOUVELLE_PARTIE pot=%s->%s cards=%s->%s street=%s observed=%s",
                    previous_pot,
                    current_pot,
                    current_card_count,
                    observed_card_count,
                    self.street,
                    observed_street,
                )
                return True

            self._new_party_flag = False
            LOGGER.warning(
                "SKIP baisse_pot_non_confirmee pot=%s->%s cards=%s->%s street=%s observed=%s",
                self._last_pot_amount,
                current_pot,
                current_card_count,
                observed_card_count,
                self.street,
                observed_street,
            )
            return False

        self._new_party_flag = False
        self._last_pot_amount = current_pot
        self._accept_observed_street(observed_street)
        return False

    def _observed_street(self) -> Optional[str]:
        cards = getattr(self.table, "cards", None)
        if cards is None:
            return None

        me_cards = cards.me_cards()
        board_cards = cards.board_cards()
        hero_count = sum(1 for card in me_cards if getattr(card, "formatted", None))
        board_count = sum(1 for card in board_cards if getattr(card, "formatted", None))

        if hero_count == 0 and board_count == 0:
            return "IDLE"
        if hero_count != 2:
            return None
        return GAME_STREET_BY_BOARD_COUNT.get(board_count)

    def _observed_card_count(self) -> int:
        cards = getattr(self.table, "cards", None)
        if cards is None:
            return 0

        visible_me = sum(1 for card in cards.me_cards() if getattr(card, "formatted", None))
        visible_board = sum(1 for card in cards.board_cards() if getattr(card, "formatted", None))
        return visible_me + visible_board

    def _accept_observed_street(self, observed_street: Optional[str]) -> None:
        if observed_street is None:
            return

        current_rank = GAME_STREET_ORDER.get(self.street, -1)
        observed_rank = GAME_STREET_ORDER.get(observed_street, -1)
        if observed_rank >= current_rank:
            self.street = observed_street

    def ack_new_party(self) -> None:
        if not self._pending_new_party_cleanup:
            LOGGER.debug("SKIP ack_new_party raison=aucun_reset_en_attente")
            return
        LOGGER.info("debut reset_partie street=%s pot=%s", self.street, self._last_pot_amount)
        self.table.New_Party()
        self.etat.cards.reset()
        self.etat.players.reset()
        self.street = "IDLE"
        self._pending_new_party_cleanup = False
        self._new_party_flag = False
        LOGGER.info("fin reset_partie status=ok street=%s", self.street)

    @property
    def new_party_detected(self) -> bool:
        return self._new_party_flag

    





    def update_from_capture(
        self,
        *,
        table_capture: Optional[Mapping[str, Any]] = None,
        regions: Optional[Mapping[str, Any]] = None,
        templates: Optional[Mapping[str, Any]] = None,
        reference_path: Optional[str] = None,
    ) -> None:
        """Injecte des paramètres de capture dans l'état courant."""

        self.table.captures.update_from_coordinates(
            table_capture=table_capture,
            regions=regions,
            templates=templates,
            reference_path=reference_path,
        )

    def add_card_observation(self, base_key: str, observation: CardObservation) -> None:
        """Enregistre une observation de carte pour inspection ultérieure."""

        card = Card()
        card.apply_observation(
            observation.value,
            observation.suit,
            observation.value_score,
            observation.suit_score,
        )
        self.table.captures.record_observation(base_key, card)
        
    @classmethod
    def for_script(cls, script_name: str) -> "Game":
        """Construit un état de jeu léger pour un script donné."""

        game = cls()
        name = Path(script_name).name
        usage = SCRIPT_STATE_USAGE.get(name)
        if not usage:
            return game

        portions = usage.portions
        if StatePortion.CARDS not in portions:
            game.table.cards = CardsState()
        if StatePortion.BUTTONS not in portions:
            game.table.buttons = Buttons()
        if StatePortion.CAPTURES not in portions:
            game.table.captures = CaptureState()
        return game
   

__all__ = [
    "Game",
    "CardObservation",
    "CardsState",
    "Buttons",
    "CaptureState",
]

```
### objet/services/script_state.py
```python
"""Descriptions des portions d'état consommées par les différents scripts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet

__all__ = [
    "StatePortion",
    "ScriptStateUsage",
    "SCRIPT_STATE_USAGE",
    "describe_scripts",
]


class StatePortion(str, Enum):
    """Portions logiques de l'état de jeu consommées par les scripts."""

    CARDS = "cards"
    BUTTONS = "buttons"
    METRICS = "metrics"
    CAPTURES = "captures"


@dataclass(frozen=True)
class ScriptStateUsage:
    """Description des portions d'état nécessaires à un script."""

    name: str
    portions: FrozenSet[StatePortion]
    description: str


SCRIPT_STATE_USAGE: Dict[str, ScriptStateUsage] = {
    "capture_cards.py": ScriptStateUsage(
        name="capture_cards.py",
        portions=frozenset({StatePortion.CARDS, StatePortion.CAPTURES}),
        description="Extraction et reconnaissance des cartes depuis une capture.",
    ),
    "Crop_Video_Frames.py": ScriptStateUsage(
        name="Crop_Video_Frames.py",
        portions=frozenset({StatePortion.CAPTURES}),
        description="Découpe périodique des captures vidéo à partir des paramètres de table.",
    ),
    "crop_core.py": ScriptStateUsage(
        name="crop_core.py",
        portions=frozenset({StatePortion.CAPTURES}),
        description="Fonctions communes de capture/crop et outils de validation géométrique.",
    ),
    "position_zones.py": ScriptStateUsage(
        name="position_zones.py",
        portions=frozenset(
            {
                StatePortion.CAPTURES,
                StatePortion.CARDS,
                StatePortion.BUTTONS,
                StatePortion.METRICS,
            }
        ),
        description="Éditeur Tk classique des zones OCR (cartes, boutons, métriques).",
    ),
    "position_zones_ctk.py": ScriptStateUsage(
        name="position_zones_ctk.py",
        portions=frozenset(
            {
                StatePortion.CAPTURES,
                StatePortion.CARDS,
                StatePortion.BUTTONS,
                StatePortion.METRICS,
            }
        ),
        description="Éditeur CustomTkinter des zones OCR (cartes, boutons, métriques).",
    ),
    "zone_project.py": ScriptStateUsage(
        name="zone_project.py",
        portions=frozenset(
            {
                StatePortion.CAPTURES,
                StatePortion.CARDS,
                StatePortion.BUTTONS,
                StatePortion.METRICS,
            }
        ),
        description="Modèle et opérations associées aux projets de zones OCR.",
    ),
    "copy_python_sources.py": ScriptStateUsage(
        name="copy_python_sources.py",
        portions=frozenset(),
        description="Outil utilitaire sans dépendance sur l'état de jeu.",
    ),
}


def describe_scripts() -> Dict[str, Dict[str, str]]:
    """Retourne un dictionnaire sérialisable listant les usages déclarés."""

    return {
        name: {
            "portions": sorted(usage.portions),
            "description": usage.description,
        }
        for name, usage in SCRIPT_STATE_USAGE.items()
    }

```
### objet/services/table.py
```python
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
        for index, card in enumerate(self.cards.me, start=1):
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
                "SCAN carte zone=main index=%s value=%s suit=%s formatted=%s score_value=%.3f score_suit=%.3f",
                index,
                value,
                suit,
                card.formatted,
                confidence_value,
                confidence_suit,
            )
        
        for index, card in enumerate(self.cards.board, start=1):
            value, suit, confidence_value, confidence_suit = self.scan.scan_carte(
                position_value=card.card_coordinates_value,
                position_suit=card.card_coordinates_suit,
                template_set=card.template_set,
            )
            if value is None and suit is None:
                LOGGER.debug("SCAN carte zone=board index=%s status=empty", index)
                continue
            card.apply_observation(
                value=value,
                suit=suit,
                value_score=confidence_value,
                suit_score=confidence_suit,
            )
            LOGGER.debug(
                "SCAN carte zone=board index=%s value=%s suit=%s formatted=%s score_value=%.3f score_suit=%.3f",
                index,
                value,
                suit,
                card.formatted,
                confidence_value,
                confidence_suit,
            )
        for index, player in enumerate(self.players.player, start=1):
            etat , money = self.scan.scan_player(
                position_money= player.fond.coordinates_value,
                position_etat= player.coordonate_etat )
            player.apply_scan(etat,money)
            LOGGER.debug(
                "SCAN joueur index=%s etat=%s fond=%s active=%s",
                index,
                etat,
                money,
                player.is_activate(),
            )
        self.players.cal_nbr_player_start()
        self.players.cal_nbr_player_active()
            
        for index, b in enumerate(self.buttons, start=1):
            texte = self.scan.scan_bouton(position= b.coordonate)
            b.apply_scan(texte)
            LOGGER.debug(
                "SCAN bouton index=%s texte=%s etat=%s enabled=%s value=%s",
                index,
                texte,
                b.etat,
                b.enabled,
                b.value,
            )
            

        self.pot.amount = self.scan.scan_money(self.pot.coordinates_value)
        LOGGER.info(
            "fin scan_table status=ok main=%s board=%s joueurs_actifs=%s/%s boutons_actifs=%s/%s pot=%s",
            _count_detected_cards(self.cards.me_cards()),
            _count_detected_cards(self.cards.board_cards()),
            self.players.nbr_player_active,
            len(self.players.player),
            sum(1 for button in self.buttons if button.is_activate()),
            len(list(self.buttons)),
            self.pot.amount,
        )
        return True

    def New_Party(self)-> None:
        """Réinitialise l'état de la Table. et fait remonter un événement."""
        LOGGER.info("RESET table raison=nouvelle_partie")
        self.cards.reset()
        self.players.reset()
        self.buttons.reset_all()
        self.pot.reset()
        self.new_party_flag = True
        
    
        
if __name__ == "__main__":
    # Petit stub de test local
    table = Table()
    table.launch_scan()
    print("Cartes joueur:", table.cards.me_cards())
    

__all__ = ["Table"]


def _count_detected_cards(cards) -> int:
    return sum(1 for card in cards if getattr(card, "formatted", None))

```
### objet/utils/__init__.py
```python
"""Utility modules shared across the application and scripts."""

__all__ = ["calibration", "logging_config", "pyauto"]

```
### objet/utils/calibration.py
```python
"""Shared calibration helpers for screen capture tools.

This module centralises the JSON loading/parsing logic shared by the
calibration utilities as well as a couple of small image helpers.  The
functions remain dependency-light so they can be used from both
application code and standalone scripts without creating circular
imports.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from PIL import Image

__all__ = [
    "Region",
    "coerce_int",
    "clamp_bbox",
    "clamp_top_left",
    "resolve_templates",
    "load_coordinates",
    "extract_patch",
    "collect_card_patches",
    "table_capture_origin",
    "CardPatch",
]


@dataclass(frozen=True)
class Region:
    """Simple container describing a rectangular capture zone."""

    key: str
    group: str
    top_left: Tuple[int, int]
    size: Tuple[int, int]
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return the JSON-compatible representation of the region."""

        payload = {"group": self.group, "top_left": list(self.top_left)}
        payload.update(self.meta)
        return payload


def coerce_int(value: Any, default: int = 0) -> int:
    """Convert *value* to an int, falling back to *default* on failure."""

    try:
        return int(round(float(value)))
    except Exception:
        return default


def clamp_bbox(x1: int, y1: int, x2: int, y2: int, width: int, height: int) -> Tuple[int, int, int, int]:
    """Clamp a bounding box to the image boundaries."""

    x1 = max(0, min(x1, width))
    y1 = max(0, min(y1, height))
    x2 = max(0, min(x2, width))
    y2 = max(0, min(y2, height))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def clamp_top_left(x: int, y: int, w: int, h: int, W: int, H: int) -> Tuple[int, int]:
    """Ensure the rectangle starting at (x, y) stays inside (W, H)."""

    if W <= 0 or H <= 0:
        return x, y
    x = max(0, min(x, max(0, W - w)))
    y = max(0, min(y, max(0, H - h)))
    return x, y


def resolve_templates(templates: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Resolve *templates* aliases and expose a uniform mapping."""

    def get_size(name: str, seen: Optional[set] = None) -> Tuple[int, int]:
        if seen is None:
            seen = set()
        if name in seen:
            return 0, 0
        seen.add(name)
        tpl = templates.get(name, {})
        if "size" in tpl:
            w, h = tpl.get("size", [0, 0])
            return coerce_int(w), coerce_int(h)
        alias = tpl.get("alias_of")
        if alias:
            return get_size(str(alias), seen)
        return 0, 0

    def get_type(name: str, seen: Optional[set] = None) -> str:
        if seen is None:
            seen = set()
        if name in seen:
            return ""
        seen.add(name)
        tpl = templates.get(name, {})
        typ = tpl.get("type")
        if typ:
            return str(typ)
        alias = tpl.get("alias_of")
        if alias:
            return get_type(str(alias), seen)
        return ""

    def get_layout(name: str, seen: Optional[set] = None) -> Dict[str, Any]:
        if seen is None:
            seen = set()
        if name in seen:
            return {}
        seen.add(name)
        tpl = templates.get(name, {})
        layout = tpl.get("layout")
        if isinstance(layout, Mapping):
            return dict(layout)
        alias = tpl.get("alias_of")
        if alias:
            return get_layout(str(alias), seen)
        return {}

    resolved: Dict[str, Dict[str, Any]] = {}
    for group in templates.keys():
        size = get_size(group)
        typ = get_type(group)
        layout = get_layout(group)
        payload = {"size": [size[0], size[1]], "type": typ}
        if layout:
            payload["layout"] = layout
        resolved[group] = payload
    return resolved


def _infer_template_set_from_key(key: str, group: str) -> Optional[str]:
    """Best-effort template-set inference based on the region name/group."""

    key_l = key.lower()
    group_l = group.lower()
    tokens = (key_l, group_l)
    for text in tokens:
        if "card" not in text:
            continue
        if any(hint in text for hint in ("player", "hand", "hero", "me")):
            return "hand"
        if any(hint in text for hint in ("board", "community", "table")):
            return "board"
    return None


def _normalise_region_entry(key: str, raw: Mapping[str, Any], templates: Mapping[str, Dict[str, Any]]) -> Region:
    group = str(raw.get("group", ""))
    top_left = raw.get("top_left", [0, 0])
    tpl_size = templates.get(group, {}).get("size")
    if isinstance(tpl_size, Iterable):
        tpl_vals = list(tpl_size)
    else:
        tpl_vals = []
    raw_size = raw.get("size")
    size_source: Iterable[Any]
    if tpl_vals:
        size_source = tpl_vals
    elif isinstance(raw_size, Iterable):
        size_source = raw_size
    else:
        size_source = []
    size = [0, 0]
    size_list = list(size_source)
    if size_list:
        size[0] = coerce_int(size_list[0])
    if len(size_list) >= 2:
        size[1] = coerce_int(size_list[1])
    meta = {k: v for k, v in raw.items() if k not in {"group", "top_left", "size"}}
    if "template_set" not in meta:
        inferred = _infer_template_set_from_key(key, group)
        if inferred:
            meta["template_set"] = inferred
    return Region(
        key=key,
        group=group,
        top_left=(coerce_int(top_left[0]), coerce_int(top_left[1])),
        size=(coerce_int(size[0]), coerce_int(size[1])),
        meta=dict(meta),
    )


# --- cache coordinates.json en mémoire ---------------------------------------

# Chemin par défaut : racine/config/PMU/coordinates.json
DEFAULT_COORDINATES_PATH = Path("config/PMU/coordinates.json")

_CoordinatesCacheEntry = Tuple[Dict[str, "Region"], Dict[str, Dict[str, Any]], Dict[str, Any]]
_COORDINATES_CACHE: Dict[Path, _CoordinatesCacheEntry] = {}


def load_coordinates(
    path: Path | str = DEFAULT_COORDINATES_PATH,
) -> Tuple[Dict[str, "Region"], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """
    Load a coordinates.json file.

    Retourne ``(regions, templates_resolved, table_capture)`` où ``regions``
    mappe les clés vers des :class:`Region`.

    - *path* est optionnel, par défaut `config/PMU/coordinates.json`.
    - Les résultats sont mis en cache par chemin absolu pour éviter
      de rouvrir et reparser le JSON à chaque appel.
    """
    coord_path = Path(path)
    key = coord_path.resolve()

    # 1) cache mémoire
    cached = _COORDINATES_CACHE.get(key)
    if cached is not None:
        return cached

    # 2) chargement disque
    with coord_path.open("r", encoding="utf-8") as fh:
        payload: Dict[str, Any] = json.load(fh)

    templates = payload.get("templates", {})
    resolved = resolve_templates(templates)
    raw_regions = payload.get("regions", {})
    regions: Dict[str, Region] = {
        r_key: _normalise_region_entry(r_key, raw, resolved)
        for r_key, raw in raw_regions.items()
    }
    table_capture: Dict[str, Any]
    tc_raw = payload.get("table_capture")
    if isinstance(tc_raw, Mapping):
        table_capture = dict(tc_raw)

        if "enabled" not in table_capture:
            table_capture["enabled"] = bool(table_capture)

        # Déduire les bornes absolues si absentes du JSON.
        if "bounds" not in table_capture:
            if regions:
                min_x = min(region.top_left[0] for region in regions.values())
                min_y = min(region.top_left[1] for region in regions.values())
                max_x = max(region.top_left[0] + region.size[0] for region in regions.values())
                max_y = max(region.top_left[1] + region.size[1] for region in regions.values())
                table_capture["bounds"] = [min_x, min_y, max_x, max_y]
            else:
                table_capture["bounds"] = [0, 0, 0, 0]

        bounds = table_capture.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            x1, y1, x2, y2 = (
                coerce_int(bounds[0]),
                coerce_int(bounds[1]),
                coerce_int(bounds[2]),
                coerce_int(bounds[3]),
            )
            table_capture.setdefault("origin", [x1, y1])
            table_capture.setdefault("size", [max(0, x2 - x1), max(0, y2 - y1)])
    else:
        table_capture = {}

    result: _CoordinatesCacheEntry = (regions, resolved, table_capture)
    _COORDINATES_CACHE[key] = result
    return result


@dataclass(frozen=True)
class CardPatch:
    number: Image.Image
    suit: Image.Image
    template_set: Optional[str] = None


def extract_patch(image: Image.Image, top_left: Tuple[int, int], size: Tuple[int, int], pad: int = 4) -> Image.Image:
    """Crop ``image`` around ``top_left``/``size`` with a soft *pad*."""

    x, y = map(int, top_left)
    w, h = map(int, size)
    width, height = image.size
    x1, y1 = x - pad, y - pad
    x2, y2 = x + w + pad, y + h + pad
    x1, y1, x2, y2 = clamp_bbox(x1, y1, x2, y2, width, height)
    return image.crop((x1, y1, x2, y2))


def _region_group(region: Region | Mapping[str, Any]) -> str:
    return region.group if isinstance(region, Region) else str(region.get("group", ""))


def _region_geometry(region: Region | Mapping[str, Any]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    if isinstance(region, Region):
        return region.top_left, region.size
    top_left = region.get("top_left", [0, 0])
    size = region.get("size", [0, 0])
    tl_x = coerce_int(top_left[0])
    tl_y = coerce_int(top_left[1])
    width, height = 0, 0
    if isinstance(size, Iterable):
        values = list(size)
        if values:
            width = coerce_int(values[0])
        if len(values) >= 2:
            height = coerce_int(values[1])
    return (tl_x, tl_y), (width, height)


def _region_template_set(region: Region | Mapping[str, Any]) -> Optional[str]:
    if isinstance(region, Region):
        value = region.meta.get("template_set")
    else:
        value = region.get("template_set")
    if value is None:
        return None
    value_str = str(value).strip()
    return value_str or None


def _normalise_origin(value: Any) -> Tuple[int, int]:
    if isinstance(value, Iterable):
        coords = list(value)
    else:
        coords = []
    if coords:
        ox = coerce_int(coords[0])
    else:
        ox = 0
    if len(coords) >= 2:
        oy = coerce_int(coords[1])
    else:
        oy = 0
    return ox, oy


def table_capture_origin(table_capture: Optional[Mapping[str, Any]]) -> Tuple[int, int]:
    """Return the absolute origin (top-left corner) of the calibrated table."""

    if not isinstance(table_capture, Mapping):
        return 0, 0
    origin = table_capture.get("origin")
    if origin is None:
        bounds = table_capture.get("bounds")
        if isinstance(bounds, Iterable):
            origin = list(bounds)[:2]
    return _normalise_origin(origin)


def _should_rebase_to_origin(
    image: Image.Image,
    table_capture: Optional[Mapping[str, Any]],
) -> Tuple[bool, Tuple[int, int]]:
    if not isinstance(table_capture, Mapping):
        return False, (0, 0)

    origin = table_capture_origin(table_capture)
    size_raw = table_capture.get("size") if isinstance(table_capture, Mapping) else None
    if isinstance(size_raw, Iterable):
        size_vals = list(size_raw)
    else:
        size_vals = []
    if len(size_vals) >= 2:
        capture_w = coerce_int(size_vals[0])
        capture_h = coerce_int(size_vals[1])
    else:
        capture_w = capture_h = 0

    if capture_w <= 0 or capture_h <= 0:
        return False, origin

    width, height = image.size
    tol = 2
    if abs(width - capture_w) <= tol and abs(height - capture_h) <= tol:
        return True, origin
    return False, origin


def collect_card_patches(
    table_img: Image.Image,
    regions: Mapping[str, Region | Mapping[str, Any]],
    *,
    pad: int = 4,
    groups_numbers: Tuple[str, ...] = ("player_card_number", "board_card_number"),
    groups_suits: Tuple[str, ...] = ("player_card_symbol", "board_card_symbol"),
    table_capture: Optional[Mapping[str, Any]] = None,
    offset: Tuple[int, int] = (0, 0),
) -> Dict[str, CardPatch]:
    """Return ``{base_key: CardPatch}`` for recognised card regions.

    The implementation walks through *regions* a single time and relies on
    :func:`extract_patch` to perform the actual cropping, keeping the
    bookkeeping logic light-weight while still supporting both
    :class:`Region` objects and plain ``dict`` entries.
    """

    slots: Dict[str, Dict[str, object]] = {}

    rebase, origin = _should_rebase_to_origin(table_img, table_capture)
    ox, oy = origin
    dx, dy = map(int, offset)

    for key, region in regions.items():
        group = _region_group(region)
        slot: Optional[str] = None
        base_key: Optional[str] = None
        if group in groups_numbers:
            slot = "number"
            base_key = key.replace("_number", "")
        elif group in groups_suits:
            slot = "symbol"
            base_key = key.replace("_symbol", "")
        else:
            continue

        if not slot or not base_key:
            continue

        top_left, size = _region_geometry(region)
        tx, ty = top_left
        tx -= dx
        ty -= dy
        if rebase:
            tx -= ox
            ty -= oy
        patch = extract_patch(table_img, (tx, ty), size, pad=pad)
        entry = slots.setdefault(base_key, {})
        entry[slot] = patch
        tpl = _region_template_set(region)
        if tpl:
            entry.setdefault("_meta", {})
            meta = entry["_meta"]
            if isinstance(meta, dict):
                meta.setdefault("template_set", tpl)

    out: Dict[str, CardPatch] = {}
    for base, mapping in slots.items():
        num = mapping.get("number")
        suit = mapping.get("symbol")
        if isinstance(num, Image.Image) and isinstance(suit, Image.Image):
            tpl_set = None
            meta = mapping.get("_meta")
            if isinstance(meta, dict):
                value = meta.get("template_set")
                tpl_set = str(value).strip() if value is not None else None
                if tpl_set == "":
                    tpl_set = None
            out[base] = CardPatch(number=num, suit=suit, template_set=tpl_set)
    return out




BBox = Tuple[int, int, int, int]  # (x, y, w, h)


def bbox_from_region(region: Optional["Region"]) -> Optional[BBox]:
    if region is None:
        return None
    x, y = map(int, region.top_left)
    w, h = map(int, region.size)
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h

```
### objet/utils/capture.py
```python
"""Gestion de l'état des captures et paramètres OCR."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from objet.entities.card import Card


@dataclass
class CaptureState:
    """Paramètres liés aux captures et aux zones OCR."""

    table_capture: Dict[str, Any] = field(default_factory=dict)
    regions: "OrderedDict[str, Any]" = field(default_factory=OrderedDict)
    templates: Dict[str, Any] = field(default_factory=dict)
    reference_path: Optional[str] = None
    card_observations: Dict[str, Card] = field(default_factory=dict)
    workflow: Optional[str] = None

    def update_from_coordinates(
        self,
        *,
        table_capture: Optional[Mapping[str, Any]] = None,
        regions: Optional[Mapping[str, Any]] = None,
        templates: Optional[Mapping[str, Any]] = None,
        reference_path: Optional[str] = None,
    ) -> None:
        if table_capture is not None:
            self.table_capture = dict(table_capture)
        if regions is not None:
            self.regions = OrderedDict(regions)
        if templates is not None:
            self.templates = dict(templates)
        if reference_path is not None:
            self.reference_path = reference_path

    def record_observation(self, base_key: str, observation: Card) -> None:
        self.card_observations[base_key] = observation

    @property
    def size(self) -> Optional[List[int]]:
        if not isinstance(self.table_capture, dict):
            return None
        size = self.table_capture.get("size")
        if isinstance(size, (list, tuple)) and len(size) == 2:
            return [int(size[0]), int(size[1])]
        bounds = self.bounds
        if bounds and len(bounds) == 4:
            x1, y1, x2, y2 = bounds
            return [int(x2 - x1), int(y2 - y1)]
        return None

    @property
    def ref_offset(self) -> Optional[List[int]]:
        if not isinstance(self.table_capture, dict):
            return None
        offset = self.table_capture.get("ref_offset")
        if isinstance(offset, (list, tuple)) and len(offset) == 2:
            return [int(offset[0]), int(offset[1])]
        origin = self.origin
        if origin and len(origin) == 2:
            return [int(origin[0]), int(origin[1])]
        return None

    @property
    def bounds(self) -> Optional[List[int]]:
        if not isinstance(self.table_capture, dict):
            return None
        bounds = self.table_capture.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            return [int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3])]
        return None

    @property
    def origin(self) -> Optional[List[int]]:
        if not isinstance(self.table_capture, dict):
            return None
        origin = self.table_capture.get("origin")
        if isinstance(origin, (list, tuple)) and len(origin) == 2:
            return [int(origin[0]), int(origin[1])]
        bounds = self.bounds
        if bounds and len(bounds) == 4:
            return bounds[:2]
        return None


__all__ = ["CaptureState"]

```
### objet/utils/logging_config.py
```python
"""Configuration de logging centralisee pour l'application."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator


APP_LOGGER_NAME = "aide_decision"
DEFAULT_LOG_DIR = Path("logs")
DEFAULT_LOG_FILE = "app.log"
MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

FILE_FORMAT = "%(asctime)s %(levelname)s %(message)s"
CONSOLE_FORMAT = "%(message)s"
TIME_FORMAT = "%H:%M:%S"


def get_logger(name: str | None = None) -> logging.Logger:
    """Retourne un child logger de l'application."""

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    if not name:
        return app_logger
    clean_name = name.removeprefix(f"{APP_LOGGER_NAME}.")
    return app_logger.getChild(clean_name)


def configure_logging(
    *,
    log_dir: Path | str = DEFAULT_LOG_DIR,
    force: bool = False,
) -> logging.Logger:
    """Configure la console INFO+ et le fichier rotatif DEBUG+."""

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False

    if app_logger.handlers and not force:
        return app_logger

    _clear_handlers(app_logger)

    file_handler = RotatingFileHandler(
        log_path / DEFAULT_LOG_FILE,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=TIME_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT))

    app_logger.addHandler(file_handler)
    app_logger.addHandler(console_handler)
    return app_logger


@contextmanager
def session_log(
    operation: str,
    *,
    log_dir: Path | str = DEFAULT_LOG_DIR,
) -> Iterator[Path]:
    """Ajoute temporairement un fichier dedie aux logs d'une operation."""

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_path = log_path / f"{operation}_{timestamp}.log"

    handler = logging.FileHandler(session_path, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=TIME_FORMAT))

    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.setLevel(logging.DEBUG)
    app_logger.propagate = False
    app_logger.addHandler(handler)
    try:
        yield session_path
    finally:
        app_logger.removeHandler(handler)
        handler.close()


def log_path_value(path: Path | str) -> str:
    """Formate un chemin de log stable pour les messages cle=valeur."""

    try:
        return str(Path(path).relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

```
### objet/utils/pyauto.py
```python
"""Helpers built around :mod:`pyautogui` usable from app code and scripts."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

import cv2
import numpy as np
import pyautogui
from PIL import Image

HaystackType = Union[np.ndarray, Image.Image]
NeedleType = Union[str, Path, Image.Image]

__all__ = ["locate_in_image"]


def _to_pil_rgb(img: HaystackType, assume_bgr: bool = False) -> Image.Image:
    """Convert ``img`` into a :class:`PIL.Image.Image` in RGB mode."""

    if isinstance(img, Image.Image):
        return img.convert("RGB")

    if not isinstance(img, np.ndarray):
        raise TypeError(f"Unsupported image type: {type(img)}")

    arr = img
    if arr.ndim == 2:
        # grayscale -> RGB
        return Image.fromarray(arr).convert("RGB")

    if arr.ndim == 3 and arr.shape[2] == 3:
        if assume_bgr:
            arr_rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        else:
            arr_rgb = arr
        return Image.fromarray(arr_rgb)

    raise ValueError(f"Unsupported array shape: {arr.shape}")


def locate_in_image(
    haystack: HaystackType,
    needle: NeedleType,
    *,
    assume_bgr: bool = False,
    grayscale: bool = False,
    confidence: float = 0.9,
) -> Optional[Tuple[int, int, int, int]]:
    """Locate ``needle`` inside ``haystack`` using ``pyautogui.locate``."""

    haystack_pil = _to_pil_rgb(haystack, assume_bgr=assume_bgr)

    if isinstance(needle, (str, Path)):
        needle_pil = Image.open(needle).convert("RGB")
    elif isinstance(needle, Image.Image):
        needle_pil = needle.convert("RGB")
    else:
        raise TypeError(f"Unsupported needle type: {type(needle)}")

    box = pyautogui.locate(
        needle_pil,
        haystack_pil,
        grayscale=grayscale,
        confidence=confidence,
    )
    if box is None:
        return None

    return int(box.left), int(box.top), int(box.width), int(box.height)

```
### objet/utils/state_utils.py
```python
"""Utilitaires communs pour la gestion des états."""
from __future__ import annotations

from typing import Any, Mapping, Optional


def extract_scan_value(scan_table: Mapping[str, Any], key: str) -> Optional[str]:
    raw = scan_table.get(key)
    if isinstance(raw, Mapping):
        return raw.get("value")
    return raw


__all__ = ["extract_scan_value"]

```
### scripts/_utils.py
```python
"""Compatibility layer for calibration helpers used by legacy scripts."""
from __future__ import annotations

from objet.utils.calibration import (
    CardPatch,
    Region,
    clamp_bbox,
    clamp_top_left,
    coerce_int,
    extract_patch,
    collect_card_patches,
    load_coordinates,
    resolve_templates,
    table_capture_origin,
)

__all__ = [
    "CardPatch",
    "Region",
    "coerce_int",
    "clamp_bbox",
    "clamp_top_left",
    "resolve_templates",
    "load_coordinates",
    "extract_patch",
    "collect_card_patches",
    "table_capture_origin",
]

```
### scripts/capture_cards.py
```python
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
    parser.add_argument("--dump", action="store_true", help="Sauver extraits dans debug/")
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
    debug_dir = auto["game_dir"] / "debug" / "cards"
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
            _save_png(debug_dir / f"{base_key}_number.png", patch_num)
            _save_png(debug_dir / f"{base_key}_symbol.png", patch_suit)
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

```
### scripts/crop_core.py
```python
import sys
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image


# ==============================
# crop_core.py – Coeur mémoire (size + ref_offset)
# ==============================
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Logger / debug helpers
LOGGER = logging.getLogger(__name__)


@dataclass
class CropDebug:
    """Debug information emitted when computing a crop."""

    ref_point: Optional[Tuple[int, int]] = None
    ref_score: Optional[float] = None
    origin_raw: Optional[Tuple[int, int]] = None
    origin: Optional[Tuple[int, int]] = None
    clamp_applied: Optional[bool] = None
    anchor_expected: Optional[Tuple[int, int]] = None
    anchor_found: Optional[Tuple[int, int]] = None
    anchor_score: Optional[float] = None
    anchor_geom_ok: Optional[bool] = None
    failure: Optional[str] = None

    def to_log_dict(self) -> Dict[str, Union[int, float, str, Tuple[int, int], None]]:
        data: Dict[str, Union[int, float, str, Tuple[int, int], None]] = asdict(self)
        return {k: v for k, v in data.items() if v is not None}


# ---------- Matching ----------

def find_ref_point(screenshot_img: Image.Image, reference_img: Image.Image) -> Tuple[int, int]:
    """Renvoie (x,y) du coin haut-gauche de `reference_img` dans `screenshot_img`."""
    scr_gray = cv2.cvtColor(np.array(screenshot_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    ref_gray = cv2.cvtColor(np.array(reference_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(scr_gray, ref_gray, cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(result)
    return int(loc[0]), int(loc[1])


def find_crop_top_left_by_matching(screenshot_img: Image.Image, crop_img: Image.Image) -> Tuple[int, int]:
    """Retrouve (x,y) du crop attendu dans le screenshot par corrélation."""
    scr_gray = cv2.cvtColor(np.array(screenshot_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    crop_gray = cv2.cvtColor(np.array(crop_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    result = cv2.matchTemplate(scr_gray, crop_gray, cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(result)
    return int(loc[0]), int(loc[1])


def _match_top_left_and_score(
    src_img: Image.Image,
    tmpl_img: Image.Image,
    method: int = cv2.TM_CCOEFF_NORMED,
) -> Tuple[Tuple[int, int], float]:
    """Retourne ((x,y), score) du meilleur match de tmpl_img dans src_img.
    Le score est normalisé: plus haut = meilleur, quel que soit le method.
    """
    src_gray = cv2.cvtColor(np.array(src_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    tpl_gray = cv2.cvtColor(np.array(tmpl_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    res = cv2.matchTemplate(src_gray, tpl_gray, method)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    if method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
        score = 1.0 - float(min_val)
        loc = min_loc
    else:
        score = float(max_val)
        loc = max_loc
    return (int(loc[0]), int(loc[1])), float(score)


# ---------- Paramètres internes (non exposés) ----------
_REF_METHOD = cv2.TM_CCOEFF_NORMED
_REF_THRESHOLD = 0.80          # seuil de détection plein écran
_INSIDE_THRESHOLD = 0.80       # seuil de détection dans le crop
_GEOM_TOL = 1                  # tolérance géométrique intra-crop (px)


# ---------- Géométrie ----------

def _clamp_box(box: Tuple[int, int, int, int], size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    W, H = size
    x1 = max(0, min(x1, W))
    y1 = max(0, min(y1, H))
    x2 = max(0, min(x2, W))
    y2 = max(0, min(y2, H))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def _clamp_origin(x0: int, y0: int, size: Tuple[int, int], canvas: Tuple[int, int]) -> Tuple[int, int]:
    W, H = canvas
    w, h = size
    x0 = max(0, min(x0, max(0, W - w)))
    y0 = max(0, min(y0, max(0, H - h)))
    return x0, y0


# ---------- Crop runtime (mémoire) ----------

def crop_from_size_and_offset(
    screenshot_img: Image.Image,
    size: Tuple[int, int],
    ref_offset: Tuple[int, int],
    *,
    reference_img: Image.Image,
) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int]]]:
    return _crop_from_size_and_offset(
        screenshot_img,
        size,
        ref_offset,
        reference_img=reference_img,
        return_details=False,
    )


def _crop_from_size_and_offset(
    screenshot_img: Image.Image,
    size: Tuple[int, int],
    ref_offset: Tuple[int, int],
    *,
    reference_img: Image.Image,
    return_details: bool,
) -> Union[
    Tuple[Optional[Image.Image], Optional[Tuple[int, int]]],
    Tuple[Optional[Image.Image], Optional[Tuple[int, int]], CropDebug],
]:
    """Retourne le crop et éventuellement les informations de debug."""

    debug = CropDebug()

    W, H = int(size[0]), int(size[1])
    ox, oy = int(ref_offset[0]), int(ref_offset[1])
    if W <= 0 or H <= 0:
        raise ValueError("Invalid size; width/height must be > 0")

    # 1) Détection de l'ancre sur le screenshot
    (rx, ry), score = _match_top_left_and_score(screenshot_img, reference_img, method=_REF_METHOD)
    debug.ref_point = (rx, ry)
    debug.ref_score = score
    if score < _REF_THRESHOLD:
        debug.failure = "anchor_score_below_threshold"
        return _maybe_with_details(None, None, debug, return_details)

    # 2) Calcul du crop (avec clamp)
    x0_raw, y0_raw = rx - ox, ry - oy
    x0, y0 = _clamp_origin(x0_raw, y0_raw, (W, H), screenshot_img.size)
    x1, y1 = x0 + W, y0 + H
    crop = screenshot_img.crop((x0, y0, x1, y1))

    debug.origin_raw = (x0_raw, y0_raw)
    debug.origin = (x0, y0)
    debug.clamp_applied = bool((x0 != x0_raw) or (y0 != y0_raw))

    # 3) Validation intra-crop (obligatoire, non paramétrable)
    ref_w, ref_h = reference_img.size
    ax_exp, ay_exp = rx - x0, ry - y0  # position attendue de l’ancre dans le crop
    debug.anchor_expected = (ax_exp, ay_exp)

    # L’ancre doit tenir entièrement dans le crop
    if not (0 <= ax_exp <= W - ref_w and 0 <= ay_exp <= H - ref_h):
        debug.failure = "anchor_outside_crop"
        return _maybe_with_details(None, None, debug, return_details)

    # Matching dans le crop
    (ax_found, ay_found), inside_score = _match_top_left_and_score(crop, reference_img, method=_REF_METHOD)
    ok_score = inside_score >= _INSIDE_THRESHOLD
    ok_geom = (abs(ax_found - ax_exp) <= _GEOM_TOL) and (abs(ay_found - ay_exp) <= _GEOM_TOL)

    debug.anchor_found = (ax_found, ay_found)
    debug.anchor_score = inside_score
    debug.anchor_geom_ok = bool(ok_geom)

    if not (ok_score and ok_geom):
        debug.failure = "anchor_validation_failed"
        return _maybe_with_details(None, None, debug, return_details)

    return _maybe_with_details(crop, (x0, y0), debug, return_details)


def _maybe_with_details(
    crop: Optional[Image.Image],
    origin: Optional[Tuple[int, int]],
    debug: CropDebug,
    return_details: bool,
) -> Union[
    Tuple[Optional[Image.Image], Optional[Tuple[int, int]]],
    Tuple[Optional[Image.Image], Optional[Tuple[int, int]], CropDebug],
]:
    if return_details:
        return crop, origin, debug
    return crop, origin


def crop_from_size_and_offset_with_debug(
    screenshot_img: Image.Image,
    size: Tuple[int, int],
    ref_offset: Tuple[int, int],
    *,
    reference_img: Image.Image,
) -> Tuple[Optional[Image.Image], Optional[Tuple[int, int]], CropDebug]:
    return _crop_from_size_and_offset(
        screenshot_img,
        size,
        ref_offset,
        reference_img=reference_img,
        return_details=True,
    )


def crop_and_save(
    screenshot_img: Image.Image,
    size: Tuple[int, int],
    ref_offset: Tuple[int, int],
    *,
    reference_img: Image.Image,
    output_path: Path,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Optional[Tuple[int, int]], CropDebug]:
    log = logger or LOGGER
    crop, origin, debug = crop_from_size_and_offset_with_debug(
        screenshot_img,
        size,
        ref_offset,
        reference_img=reference_img,
    )

    log_payload = {
        "size": tuple(map(int, size)),
        "ref_offset": tuple(map(int, ref_offset)),
        **debug.to_log_dict(),
    }

    if crop is None or origin is None:
        failure = debug.failure or "unknown"
        log.warning(
            "crop_and_save failed: %s | params=%s",
            failure,
            log_payload,
        )
        return None, debug

    x0, y0 = origin
    bbox = (x0, y0, x0 + crop.size[0], y0 + crop.size[1])
    log_payload.update({"origin": origin, "bbox": bbox})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path)
    log.info("crop saved origin=%s bbox=%s params=%s", origin, bbox, log_payload)
    return origin, debug


# ---------- Comparaison / Vérif ----------

def _compare_images(img_a: Image.Image, img_b: Image.Image, pix_tol: int = 0) -> Tuple[bool, Dict[str, float]]:
    a = np.array(img_a.convert("RGB"))
    b = np.array(img_b.convert("RGB"))
    if a.shape != b.shape:
        return False, {"reason": "size_mismatch", "a_w": float(a.shape[1]), "a_h": float(a.shape[0]), "b_w": float(b.shape[1]), "b_h": float(b.shape[0])}
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    max_diff = int(diff.max())
    mean_diff = float(diff.mean())
    return (max_diff <= int(pix_tol)), {"max_diff": float(max_diff), "mean_diff": float(mean_diff)}



def verify_geom(
    screenshot_img: Image.Image,
    expected_img: Image.Image,
    size: Tuple[int, int],
    ref_offset: Tuple[int, int],
    *,
    reference_img: Image.Image,
    geom_tol: int = 1,
    pix_tol: int = 0,
) -> Tuple[bool, Dict[str, float]]:
    """Vérifie l'ALIGNEMENT géométrique:
       - prédit (px,py) via (size, ref_offset, ancre)
       - mesure (mx,my) en matchant expected_img dans screenshot
       OK si |px-mx|<=geom_tol et |py-my|<=geom_tol.
       Ajoute stats pixel (max_diff/mean_diff) à titre informatif.
    """
    # 1) prédiction via runtime (tolérant)
    crop_pred, origin = crop_from_size_and_offset(
        screenshot_img, size, ref_offset, reference_img=reference_img
    )
    if crop_pred is None or origin is None:
        return False, {"reason": "anchor_not_found_or_invalid"}

    px, py = origin

    # 2) mesure via matching
    mx, my = find_crop_top_left_by_matching(screenshot_img, expected_img)

    dx, dy = int(px - mx), int(py - my)
    ok_geom = (abs(dx) <= int(geom_tol)) and (abs(dy) <= int(geom_tol))

    ok_pix, pix_stats = _compare_images(crop_pred, expected_img, pix_tol)
    stats = {"pred_top_left": (px, py), "match_top_left": (mx, my), "dx": float(dx), "dy": float(dy), **pix_stats}
    return ok_geom, stats


# ---------- Inference offset ----------

def infer_size_and_offset(
    screenshot_img: Image.Image,
    expected_img: Image.Image,
    reference_img: Image.Image,
) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """Calcule:
      - size = expected_img.size
      - crop_top_left_abs (cx,cy) en matchant `expected_img` dans le screenshot
      - ref_point_abs (rx,ry)
      - ref_offset = (rx-cx, ry-cy)
    Retourne: (size, ref_offset, (cx,cy), (rx,ry))
    """
    size = expected_img.size
    cx, cy = find_crop_top_left_by_matching(screenshot_img, expected_img)
    rx, ry = find_ref_point(screenshot_img, reference_img)
    ref_offset = (rx - cx, ry - cy)
    return size, ref_offset, (cx, cy), (rx, ry)


# ---------- JSON helpers ----------

def save_capture_json(path: Path, size: Tuple[int, int], ref_offset: Tuple[int, int]) -> None:
    data = {}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["table_capture"] = {"size": [int(size[0]), int(size[1])], "ref_offset": [int(ref_offset[0]), int(ref_offset[1])]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==========================================
# configure_table_crop.py — CLI de validation (geom d'abord)
# ==========================================
import argparse
from typing import Optional, List

from PIL import Image

# from crop_core import (
#   find_ref_point, find_crop_top_left_by_matching, crop_from_size_and_offset,
#   verify_geom, infer_size_and_offset, save_capture_json
# )


def _load_image(path: Path) -> Image.Image:
    return Image.open(path)


def _find_first(game_dir: Path, base: str, exts: Optional[List[str]] = None) -> Optional[Path]:
    exts = exts or [".png", ".jpg", ".jpeg"]
    for ext in exts:
        p = game_dir / f"{base}{ext}"
        if p.exists():
            return p
    return None


def _auto_paths_for_game(game: str, game_dir_opt: Optional[str]) -> dict:
    game_dir = Path(game_dir_opt) if game_dir_opt else Path("config") / (game or "PMU")
    screenshot = _find_first(game_dir, "test_crop", [".jpg", ".png", ".jpeg"])  # plein écran
    expected = _find_first(game_dir, "test_crop_result", [".png", ".jpg", ".jpeg"])  # fenêtre attendue
    reference = _find_first(game_dir, "anchor", [".png", ".jpg", ".jpeg"])  # gabarit ref
    output = game_dir / "coordinates.json"
    return {"game_dir": game_dir, "screenshot": screenshot, "expected": expected, "reference": reference, "output": output}


def parse_size(s: str) -> Tuple[int, int]:
    s = s.lower().replace("x", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--size requires WxH or W,H")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError as e:
        raise argparse.ArgumentTypeError("--size values must be integers") from e
    return w, h


def parse_offset(s: str) -> Tuple[int, int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--ref-offset requires two integers: ox,oy")
    try:
        ox, oy = int(parts[0]), int(parts[1])
    except ValueError as e:
        raise argparse.ArgumentTypeError("--ref-offset values must be integers") from e
    return ox, oy


def _with_debug_suffix(p: Path) -> Path:
    return p.with_name(p.stem + "_debug" + p.suffix)


def _save_any(path: Path, img: Image.Image) -> None:
    # Corrige "cannot write mode RGBA as JPEG"
    if path.suffix.lower() in (".jpg", ".jpeg") and img.mode == "RGBA":
        img = img.convert("RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Infère et valide (size, ref_offset); écrit coordinates.json (geom match)")
    parser.add_argument("--game", default="PMU", help="Game folder under config/ (default: PMU)")
    parser.add_argument("--game-dir", help="Explicit game dir (overrides --game)")
    parser.add_argument("--size", type=parse_size, help="Override size WxH; default = expected image size")
    parser.add_argument("--ref-offset", type=parse_offset, help="Override ref offset ox,oy; default = inferred from images")
    parser.add_argument("--runs", type=int, default=10, help="Repeat verification N times (default: 10)")
    parser.add_argument("--pix-tol", type=int, default=0, help="Pixel tolerance (info only)")
    parser.add_argument("--geom-tol", type=int, default=1, help="Geometric tolerance in pixels (default: 1)")
    parser.add_argument("--write-crop", help="Optional path to save one computed crop for inspection")

    args = parser.parse_args(argv)

    auto = _auto_paths_for_game(args.game, args.game_dir)
    screenshot_path = auto["screenshot"]
    expected_path = auto["expected"]
    reference_path = auto["reference"]
    output_path = auto["output"]

    if screenshot_path is None or not screenshot_path.exists():
        raise SystemExit("ERROR: screenshot test not found (test_crop.jpg|.png)")
    if expected_path is None or not expected_path.exists():
        raise SystemExit("ERROR: expected crop not found (test_crop_result.*)")
    if reference_path is None or not reference_path.exists():
        raise SystemExit("ERROR: reference template not found (me.*)")

    scr = _load_image(screenshot_path).convert("RGBA")
    exp = _load_image(expected_path).convert("RGBA")
    ref = _load_image(reference_path).convert("RGBA")

    from objet.services.game import Game
    game = Game.for_script(Path(__file__).name)

    # 1) Taille + offset (inférence par défaut)
    if args.size and args.ref_offset:
        size = args.size
        ref_offset = args.ref_offset
        print("[override] size:", size, "ref_offset:", ref_offset)
    else:
        from __main__ import infer_size_and_offset  # if same file; adjust import if split
        size_inf, ref_off_inf, crop_pos, ref_pos = infer_size_and_offset(scr, exp, ref)
        size = args.size if args.size else size_inf
        ref_offset = args.ref_offset if args.ref_offset else ref_off_inf
        print("[infer] crop_top_left:", crop_pos, "ref_point:", ref_pos, "-> ref_offset:", ref_off_inf, "size:", size_inf)

    # 2) Écrit JSON (taille + ref_offset)
    from __main__ import save_capture_json  # adjust import if split
    save_capture_json(output_path, size, ref_offset)
    print("Wrote:", output_path)
    print("table_capture.size:", list(size), "table_capture.ref_offset:", list(ref_offset))
    game.update_from_capture(table_capture={"size": list(size), "ref_offset": list(ref_offset)})

    # 3) Vérification répétée (géométrie en priorité)
    from __main__ import verify_geom, crop_from_size_and_offset
    ok_count = 0
    last_stats = {}
    for i in range(int(args.runs)):
        ok, stats = verify_geom(
            scr, exp, size, ref_offset,
            reference_img=ref,
            geom_tol=int(args.geom_tol),
            pix_tol=int(args.pix_tol),
        )
        last_stats = stats
        print(f"run {i+1:02d}: ", "OK" if ok else "FAIL", stats)
        if ok:
            ok_count += 1

    # 4) Sauvegarde debug (si calcul possible)
    crop, origin = crop_from_size_and_offset(scr, size, ref_offset, reference_img=ref)
    debug_path = _with_debug_suffix(expected_path)
    if crop is not None and origin is not None:
        _save_any(debug_path, crop)
        print("Wrote computed crop (debug):", debug_path, "origin:", origin)
        if args.write_crop:
            _save_any(Path(args.write_crop), crop)
            print("Wrote computed crop (custom):", args.write_crop)
    else:
        print("No debug crop written: anchor not found/validated.")

    print(f"Summary: {ok_count}/{args.runs} OK (geom_tol={args.geom_tol}, pix_tol={args.pix_tol})")
    print("Game capture context:", game.table.captures.table_capture)
    return 0 if ok_count == int(args.runs) else 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))

```
### scripts/Crop_Video_Frames.py
```python
#!/usr/bin/env python3
"""Extract full-screen frames from a calibration video at regular intervals."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Tuple

import cv2
from PIL import Image

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.services.game import Game  # type: ignore
from objet.utils.calibration import load_coordinates


def _auto_video(game_dir: Path) -> Optional[Path]:
    base = game_dir / "debug" / "cards_video"
    if base.is_file():
        return base
    if base.is_dir():
        for ext in (".avi", ".mp4", ".mkv", ".mov"):
            candidate = base / f"cards_video{ext}"
            if candidate.exists():
                return candidate
        for candidate in sorted(base.glob("*")):
            if candidate.suffix.lower() in {".avi", ".mp4", ".mkv", ".mov"}:
                return candidate
    for ext in (".avi", ".mp4", ".mkv", ".mov"):
        candidate = game_dir / "debug" / f"cards_video{ext}"
        if candidate.exists():
            return candidate
    return None


def _default_game_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "config" / "PMU",
        Path.cwd() / "config" / "PMU",
        Path.cwd().parent / "config" / "PMU",
    ]
    for candidate in candidates:
        if (candidate / "coordinates.json").exists():
            return candidate
    return candidates[0]


def _iter_time_step(cap: cv2.VideoCapture, seconds_step: float):
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1e-6:
        fps = 30.0
    step_frames = max(1, int(round(fps * float(seconds_step))))
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step_frames == 0:
            yield index, frame
        index += 1


def _ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_table_capture(game_dir: Path) -> Tuple[dict, dict, dict]:
    regions, templates, table_capture = load_coordinates(game_dir / "coordinates.json")
    return regions, templates, table_capture


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Save full-screen frames from a calibration video")
    parser.add_argument(
        "--game-dir",
        default=str(_default_game_dir()),
        help="Path to the game directory (default: auto-detected config/<game>)",
    )
    parser.add_argument(
        "--video",
        help="Explicit video path; default: game_dir/debug/cards_video/cards_video.*",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between captures (default: 3.0)",
    )
    parser.add_argument(
        "--out",
        help="Output directory (default: game_dir/debug/screens)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, ...). Default: INFO",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )
    logger = logging.getLogger("crop_video_frames")

    game_dir = Path(args.game_dir)
    out_dir = _ensure_output_dir(Path(args.out) if args.out else (game_dir / "debug" / "screens"))

    regions, templates, table_capture = _load_table_capture(game_dir)
    game = Game.for_script(Path(__file__).name)
    game.update_from_capture(
        table_capture=table_capture,
        regions={k: {"group": r.group, "top_left": r.top_left, "size": r.size} for k, r in regions.items()},
        templates=templates,
    )

    video_path = Path(args.video) if args.video else _auto_video(game_dir)
    if not video_path or not video_path.exists():
        raise SystemExit(
            f"ERROR: no video found. Put a file inside {game_dir/'debug'/'cards_video'} or pass --video"
        )

    logger.info("Using game_dir: %s", game_dir)
    logger.info("Using video:    %s", video_path)
    bounds = table_capture.get("bounds") if isinstance(table_capture, dict) else None
    if bounds:
        logger.info("Table bounds:  %s", bounds)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise SystemExit(f"ERROR: cannot open video: {video_path}")

    saved = 0
    for frame_index, frame_bgr in _iter_time_step(capture, seconds_step=float(args.interval)):
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_img = Image.fromarray(frame_rgb).convert("RGBA")
        out_path = out_dir / f"frame_{frame_index:06d}.png"
        frame_img.save(out_path)
        saved += 1
        logger.debug("Saved %s", out_path.name)

    capture.release()
    logger.info("Extraction complete: %s frames saved", saved)
    print(f"Done. {saved} frames written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

```
### scripts/identify_card.py
```python
#!/usr/bin/env python3
"""identify_card.py — labellisation incrémentale des cartes.

Parcourt les captures plein écran dans ``config/<jeu>/debug/screens``, extrait les
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
  --screens-dir   Dossier d’entrée (défaut: config/<jeu>/debug/screens)
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

    screens_dir = Path(args.screens_dir) if args.screens_dir else game_dir / "debug" / "screens"
    if not screens_dir.exists():
        print(f"ERREUR: dossier de captures introuvable ({screens_dir})")
        return 2

    regions, _, table_capture = load_coordinates(coords_path)

    # Service incrémental
    identifier = CardIdentifier(
        game_dir,
        trim=int(args.trim),
        threshold=DEFAULT_ACCEPT_THRESHOLD,
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

```
### scripts/position_zones_ctk.py
```python
# position_zones_ctk.py — UI simplifiée pour éditer les zones
# UI uniquement — la logique métier est dans zone_project.py

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import filedialog  # plus utilisé pour le save-as, mais on garde l'import

import customtkinter as ctk
from PIL import ImageTk, Image

# =========================
# Constantes "en dur"
# =========================
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DEFAULT_GAME_NAME = "PMU"
DEFAULT_IMAGE_NAME = "example_full_screen.png"

# Chemin projet pour les imports
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from objet.services.game import Game
from zone_project import ZoneProject

APP_TITLE = "Zone Editor (CustomTkinter)"


class ZoneEditorCTK:
    def __init__(self, base_dir: Optional[str] = None):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(APP_TITLE)

        # Plein écran ancré en (0, 0)
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")

        # Fermeture : aucune sauvegarde automatique
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Modèle
        self.base_dir = os.path.abspath(base_dir or str(DEFAULT_CONFIG_DIR))
        self.project = ZoneProject(Game.for_script(Path(__file__).name))

        # Image affichée
        self.tk_img: Optional[ImageTk.PhotoImage] = None
        self.base_scale: float = 1.0
        self.user_zoom: float = 0.85  # zoom par défaut
        self.scale: float = 1.0

        # Dessin
        self.rect_items: dict[str, int] = {}
        self.text_items: dict[str, int] = {}
        self.dragging_key: Optional[str] = None
        self.drag_offset: Tuple[int, int] = (0, 0)
        self._last_key: Optional[str] = None

        self._build_ui()
        self._bind_canvas_events()
        self._refresh_games_list()

    # ---------- UI ----------
    def _build_ui(self):
        # Topbar
        top = ctk.CTkFrame(self.root, corner_radius=0)
        top.pack(side="top", fill="x")

        # Jeux
        ctk.CTkLabel(top, text="Jeu:").pack(side="left", padx=(8, 4), pady=8)
        self.game_var = tk.StringVar(value="")
        self.game_menu = ctk.CTkOptionMenu(
            top, values=[""], variable=self.game_var, command=self._on_select_game
        )
        self.game_menu.pack(side="left", padx=4, pady=8)

        # Zoom
        ctk.CTkLabel(top, text="Zoom").pack(side="left", padx=(16, 4))
        self.zoom_slider = ctk.CTkSlider(
            top,
            from_=0.25,
            to=3.0,
            number_of_steps=55,
            command=lambda v: self._on_zoom_slider(float(v)),
        )
        self.zoom_slider.set(self.user_zoom)
        self.zoom_slider.pack(side="left", padx=6, pady=8)
        self.zoom_pct_label = ctk.CTkLabel(top, text="85%")
        self.zoom_pct_label.pack(side="left", padx=(6, 2))

        # Bouton "Ajuster" → remet à 85 %
        self.btn_adjust = ctk.CTkButton(
            top, text="Ajuster", width=80, command=self._zoom_85
        )
        self.btn_adjust.pack(side="left", padx=4, pady=8)

        # Enregistrer
        self.btn_save = ctk.CTkButton(
            top, text="Enregistrer", command=self._save_json, state="disabled"
        )
        self.btn_save.pack(side="left", padx=8, pady=8)

        # Main split
        main = ctk.CTkFrame(self.root)
        main.pack(side="top", fill="both", expand=True)

        # Canvas (zone d'image)
        cf = ctk.CTkFrame(main)
        cf.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)
        self.canvas = tk.Canvas(
            cf,
            bg="#F2F2F2",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        # Sidebar (toujours visible)
        side = ctk.CTkFrame(main, width=360)
        side.pack(side="right", fill="y", padx=(5, 10), pady=10)

        ctk.CTkLabel(
            side, text="Régions", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))
        self.listbox = tk.Listbox(side, height=14, exportselection=False)
        self.listbox.pack(fill="x", padx=12)
        self.listbox.bind("<<ListboxSelect>>", self._on_select_region_from_list)

        frm = ctk.CTkFrame(side)
        frm.pack(fill="x", padx=12, pady=12)

        ctk.CTkLabel(frm, text="Nom (clé)").grid(row=0, column=0, sticky="w")
        self.entry_name = ctk.CTkEntry(frm)
        self.entry_name.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        frm.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frm, text="Groupe").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.group_var = tk.StringVar(value="")
        self.group_menu = ctk.CTkOptionMenu(frm, values=[""], variable=self.group_var)
        self.group_menu.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="X").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.entry_x = ctk.CTkEntry(frm, width=90)
        self.entry_x.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="Y").grid(row=3, column=0, sticky="w")
        self.entry_y = ctk.CTkEntry(frm, width=90)
        self.entry_y.grid(row=3, column=1, sticky="w", padx=(8, 0))

        ctk.CTkLabel(frm, text="Largeur (groupe)").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        self.entry_w = ctk.CTkEntry(frm, width=90)
        self.entry_w.grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ctk.CTkLabel(frm, text="Hauteur (groupe)").grid(row=5, column=0, sticky="w")
        self.entry_h = ctk.CTkEntry(frm, width=90)
        self.entry_h.grid(row=5, column=1, sticky="w", padx=(8, 0))

        # Appliquer
        btns = ctk.CTkFrame(side)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_apply = ctk.CTkButton(
            btns, text="Appliquer", command=self._apply_changes, state="disabled"
        )
        self.btn_apply.pack(side="left", padx=6)

        # Entrée ↵ applique
        for e in (
            self.entry_name,
            self.entry_x,
            self.entry_y,
            self.entry_w,
            self.entry_h,
        ):
            e.bind("<Return>", lambda _e: self._apply_changes())

        # Status
        self.status = ctk.CTkLabel(self.root, text="Prêt", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=8, pady=6)

    def _bind_canvas_events(self):
        # Drag des zones (gauche)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        # Pan (main) : clic milieu OU clic droit
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

    # ---------- Jeux / fichiers ----------
    def _refresh_games_list(self):
        base = self.base_dir
        games = ZoneProject.list_games(base)
        if not games:
            self.game_menu.configure(values=[""])
            self.game_var.set("")
            return

        self.game_menu.configure(values=games)
        game_name = DEFAULT_GAME_NAME if DEFAULT_GAME_NAME in games else games[0]
        self.game_var.set(game_name)
        self._on_select_game(game_name)

    def _on_select_game(self, game_name: str):
        if not game_name:
            return

        base = self.base_dir

        # Charge la config du jeu (regions, templates, etc.)
        self.project.load_game(base, game_name)

        # Force l'image sur config/<jeu>/example_full_screen.png (si ça manque, ça plante, c'est voulu)
        game_dir = Path(base) / game_name
        candidate = game_dir / DEFAULT_IMAGE_NAME

        img = Image.open(candidate).convert("RGB")
        self.project.image = img
        self.project.image_path = str(candidate)

        # Alignement + rendu
        self._startup_align_groups()
        self._prepare_display_image()
        self._reset_canvas()
        self._redraw_all()
        self._populate_regions_list()
        self._populate_group_menu()

        self.btn_save.configure(state="normal")
        self.btn_apply.configure(state="normal")
        self.status.configure(text=f"{game_name}: {len(self.project.regions)} région(s)")

        # Auto-sélectionne la 1ère région
        keys = sorted(self.project.regions.keys())
        if keys:
            first = keys[0]
            self._last_key = first
            self._select_key_in_list(first)
            self._on_select_region_from_list()

    def _startup_align_groups(self):
        groups: dict[str, List[str]] = {}
        for k, r in self.project.regions.items():
            g = r.get("group", "")
            groups.setdefault(g, []).append(k)

        for g, keys in groups.items():
            if not self.project.group_has_lock_same_y(g):
                continue
            if not keys:
                continue
            keys_sorted = sorted(keys)
            anchor_key = keys_sorted[0]
            x, y = self.project.regions[anchor_key]["top_left"]
            self.project.set_region_pos(anchor_key, x, y)

    # ---------- Image / zoom ----------
    def _prepare_display_image(self):
        W, H = self.project.image_size
        if W == 0 or H == 0:
            return
        # 100% = 1:1
        self.base_scale = 1.0
        self._update_display_image()

    def _update_display_image(self):
        img = self.project.image
        if img is None:
            return
        # scale = zoom utilisateur, base_scale toujours 1.0
        self.scale = max(0.05, max(0.1, float(self.user_zoom)))
        disp = img.resize(
            (int(img.width * self.scale), int(img.height * self.scale)), Image.LANCZOS
        )
        self.tk_img = ImageTk.PhotoImage(disp)
        pct = int(round(self.scale * 100))
        self.zoom_pct_label.configure(text=f"{pct}%")
        self._reset_canvas()

    def _reset_canvas(self):
        self.canvas.delete("all")
        self.rect_items.clear()
        self.text_items.clear()

        if self.tk_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            # Surface virtuelle = taille de l'image → pan possible
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

    # ---------- Dessin ----------
    def _redraw_all(self):
        self.canvas.delete("all")
        self.rect_items.clear()
        self.text_items.clear()

        if self.tk_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

        W, H = self.project.image_size
        if W == 0:
            return

        s = self.scale
        for key, r in self.project.regions.items():
            group = r.get("group", "")
            w, h = self.project.get_group_size(group)
            x, y = r["top_left"]
            dx0, dy0 = int(x * s), int(y * s)
            dx1, dy1 = int((x + w) * s), int((y + h) * s)
            rid = self.canvas.create_rectangle(
                dx0, dy0, dx1, dy1, outline="#0ea5e9", width=2
            )
            tid = self.canvas.create_text(
                dx0 + 6,
                dy0 + 6,
                anchor="nw",
                text=str(r.get("label", key)),
                fill="#0ea5e9",
                font=("Segoe UI", 10, "bold"),
            )
            self.rect_items[key] = rid
            self.text_items[key] = tid

    # ---------- Liste & champs ----------
    def _populate_regions_list(self):
        self.listbox.delete(0, tk.END)
        for k in sorted(self.project.regions.keys()):
            lab = self.project.regions[k].get("label", k)
            self.listbox.insert(tk.END, f"{k}  —  {lab}")

    def _populate_group_menu(self):
        groups = sorted(list(self.project.templates_resolved.keys())) or [""]
        self.group_menu.configure(values=groups)
        if groups:
            self.group_var.set(groups[0])

    def _current_selection_key(self) -> Optional[str]:
        sel = self.listbox.curselection()
        if not sel:
            return None
        line = self.listbox.get(sel[0])
        return line.split("  —  ", 1)[0]

    def _select_key_in_list(self, key: str):
        keys = sorted(self.project.regions.keys())
        if key in keys:
            idx = keys.index(key)
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(idx)
            self.listbox.activate(idx)

    def _on_select_region_from_list(self, event=None):
        key = self._current_selection_key()
        if not key:
            return

        r = self.project.regions[key]

        self.entry_name.delete(0, tk.END)
        self.entry_name.insert(0, key)

        group = r.get("group", "")
        if group and group not in self.project.templates:
            self.project.templates[group] = {"size": [60, 40], "type": "mix"}

        # MAJ menu des groupes
        groups = sorted(list(self.project.templates_resolved.keys())) or [""]
        self.group_menu.configure(values=groups)
        if group in groups:
            self.group_var.set(group)
        elif groups:
            self.group_var.set(groups[0])

        x, y = r["top_left"]
        self.entry_x.delete(0, tk.END)
        self.entry_x.insert(0, str(int(x)))
        self.entry_y.delete(0, tk.END)
        self.entry_y.insert(0, str(int(y)))

        gw, gh = self.project.get_group_size(r.get("group", ""))
        self.entry_w.delete(0, tk.END)
        self.entry_w.insert(0, str(int(gw)))
        self.entry_h.delete(0, tk.END)
        self.entry_h.insert(0, str(int(gh)))

        self.btn_apply.configure(state="normal")
        self._last_key = key

    # ---------- Drag & drop zones (gauche) ----------
    def _region_at_point(self, x: int, y: int) -> Optional[str]:
        for key, r in self.project.regions.items():
            gw, gh = self.project.get_group_size(r.get("group", ""))
            px, py = r["top_left"]
            if px <= x <= px + gw and py <= y <= py + gh:
                return key
        return None

    def _on_mouse_down(self, event):
        s = self.scale if self.scale else 1.0
        # coord dans le repère image (pas canvas)
        x, y = int(self.canvas.canvasx(event.x) / s), int(self.canvas.canvasy(event.y) / s)
        key = self._region_at_point(x, y)
        if key:
            self.dragging_key = key
            tlx, tly = self.project.regions[key]["top_left"]
            self.drag_offset = (x - tlx, y - tly)
            self._select_key_in_list(key)
            self._on_select_region_from_list()
            self._last_key = key
        else:
            self.dragging_key = None

    def _on_mouse_drag(self, event):
        if not self.dragging_key:
            return
        key = self.dragging_key
        s = self.scale if self.scale else 1.0
        x = int(self.canvas.canvasx(event.x) / s) - self.drag_offset[0]
        y = int(self.canvas.canvasy(event.y) / s) - self.drag_offset[1]
        self.project.set_region_pos(key, x, y)
        self._redraw_group(self.project.regions[key]["group"])

        px, py = self.project.regions[key]["top_left"]
        self.entry_x.delete(0, tk.END)
        self.entry_x.insert(0, str(px))
        self.entry_y.delete(0, tk.END)
        self.entry_y.insert(0, str(py))

    def _on_mouse_up(self, event):
        self.dragging_key = None

    def _redraw_group(self, group: str):
        s = self.scale if self.scale else 1.0
        keys = [k for k, r in self.project.regions.items() if r.get("group") == group]
        for k in keys:
            r = self.project.regions[k]
            w, h = self.project.get_group_size(group)
            x, y = r["top_left"]
            dx0, dy0 = int(x * s), int(y * s)
            dx1, dy1 = int((x + w) * s), int((y + h) * s)
            rid = self.rect_items.get(k)
            tid = self.text_items.get(k)
            if rid:
                self.canvas.coords(rid, dx0, dy0, dx1, dy1)
            if tid:
                self.canvas.coords(tid, dx0 + 6, dy0 + 6)

    # ---------- Pan (main) ----------
    def _on_pan_start(self, event):
        # point de départ pour le scan
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event):
        # déplacement de la vue (viewport) sans modifier les coords des objets
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    # ---------- Actions ----------
    def _apply_changes(self):
        key = self._current_selection_key() or self._last_key
        if not key:
            return

        r = self.project.regions[key]

        # Rename
        new_key = (self.entry_name.get() or key).strip()
        if new_key and new_key != key:
            new_key = self.project.rename_region(key, new_key)
            key = new_key
            r = self.project.regions[key]
            self._last_key = key

        # Group
        group = (self.group_var.get() or r.get("group", "")).strip()
        self.project.set_region_group(key, group)

        # Position
        x = int(self.entry_x.get())
        y = int(self.entry_y.get())
        self.project.set_region_pos(key, x, y)

        # Taille (propagée au groupe)
        nw = int(self.entry_w.get())
        nh = int(self.entry_h.get())
        if nw > 0 and nh > 0:
            g = self.project.regions[key]["group"]
            self.project.set_group_size(g, nw, nh)

        self._populate_regions_list()
        g = self.project.regions[key]["group"]
        self._redraw_group(g)
        self._select_key_in_list(key)
        self._on_select_region_from_list()
        self.status.configure(text=f"Modifié: {key}")

    def _save_json(self):
        """Écrit directement config/<jeu>/coordinates.json, uniquement sur clic bouton."""
        game = self.project.current_game or DEFAULT_GAME_NAME
        out_path = os.path.join(self.base_dir, game, "coordinates.json")
        self.project.save_to(out_path)
        self.status.configure(text=f"Sauvegardé: {out_path}")

    # ---------- Fermeture ----------
    def _on_close(self):
        """Fermeture sans aucune sauvegarde implicite."""
        self.root.destroy()

    # ---------- Zoom ----------
    def _on_zoom_slider(self, value: float):
        self.user_zoom = float(value)
        self._update_display_image()
        self._redraw_all()

    def _zoom_85(self):
        """Remet le zoom à 85 % via le bouton 'Ajuster'."""
        self.user_zoom = 0.85
        self.zoom_slider.set(self.user_zoom)
        self._update_display_image()
        self._redraw_all()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ZoneEditorCTK()
    app.run()

```
### scripts/quick_setup.py
```python
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
    parser = argparse.ArgumentParser(description="Assistant de configuration rapide (zones → captures → cartes → validation)")
    parser.add_argument("--game", default="PMU", help="Nom du jeu (dossier dans config/)")
    parser.add_argument("--config-root", help="Chemin vers le dossier config/ (défaut: auto)")
    parser.add_argument("--video", help="Vidéo utilisée pour le crop et la validation")
    parser.add_argument("--screens-dir", help="Dossier de sortie des captures (défaut: config/<game>/debug/screens)")
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

    screens_dir = Path(args.screens_dir).resolve() if args.screens_dir else (game_dir / "debug" / "screens")

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
    _report_missing_cards(PROJECT_ROOT / "config" / "PMU")
    raise SystemExit(main())

```
### scripts/state_requirements.py
```python
"""Re-export of :mod:`objet.services.script_state` for CLI consumers."""
from __future__ import annotations

from objet.services.script_state import (
    SCRIPT_STATE_USAGE,
    StatePortion,
    ScriptStateUsage,
    describe_scripts,
)

__all__ = [
    "StatePortion",
    "ScriptStateUsage",
    "SCRIPT_STATE_USAGE",
    "describe_scripts",
]

```
### scripts/zone_project.py
```python
# zone_project.py
# Logique "métier" : modèle, opérations, lecture/écriture JSON, clamp
# Aucune dépendance UI. Dépend de pillow uniquement pour charger l'image.

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Mapping, Iterable
from collections import OrderedDict
from PIL import Image

from objet.services.game import Game
from _utils import clamp_top_left, coerce_int, resolve_templates


def _load_templated_json(coord_path: str) -> Dict[str, Any]:
    """Charge coordinates.json et valide le format minimal.

    Si le fichier est invalide, on laisse l'exception remonter.
    """
    with open(coord_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not (isinstance(data, dict) and "templates" in data and "regions" in data):
        raise ValueError(f"coordinates.json invalide: {coord_path}")
    return data


class ZoneProject:
    """
    Représente un "projet" de zones pour un jeu (image + zones + templates).

    Gère :
      - chargement/écriture JSON,
      - manipulations des régions,
      - tailles de groupe,
      - contraintes lock_same_y.
    """

    def __init__(self, game: Optional[Game] = None) -> None:
        self.game = game or Game.for_script(Path(__file__).name)
        self.base_dir: str = ""
        self.current_game: Optional[str] = None
        self.image_path: Optional[str] = None
        self.image: Optional[Image.Image] = None

        # Capture/table (copie initiale de la config du jeu)
        self.table_capture: Dict[str, Any] = self.game.table.captures.table_capture

        # Données décrites par le JSON
        self.templates: Dict[str, Any] = self.game.table.captures.templates
        self._templates_resolved: Dict[str, Any] = {}
        # regions : key -> {"group": str, "top_left":[x,y], "value": Any, "label": str}
        self.regions: "OrderedDict[str, Dict[str, Any]]" = self.game.table.captures.regions

    # ---------- Propriétés utiles ----------
    @property
    def image_size(self) -> Tuple[int, int]:
        if self.image is None:
            return 0, 0
        return self.image.width, self.image.height

    @property
    def templates_resolved(self) -> Dict[str, Any]:
        # recalcul léger à la demande
        return resolve_templates(self.templates)

    def get_group_size(self, group: str) -> Tuple[int, int]:
        size = self.templates_resolved.get(group, {}).get("size", [60, 40])
        return coerce_int(size[0], 60), coerce_int(size[1], 40)

    def group_has_lock_same_y(self, group: str) -> bool:
        layout = self.templates_resolved.get(group, {}).get("layout", {})
        return bool(layout.get("lock_same_y", False))

    # ---------- Découverte ----------
    @staticmethod
    def _find_expected_image(folder: str) -> Optional[str]:
        """Retourne une capture plausible pour *folder* (full screen/table)."""

        prefer_bases = [
            "test_screen",
            "test_fullscreen",
            "test_table",
            
        ]
        exts = [".png", ".jpg", ".jpeg"]

        for base in prefer_bases:
            for ext in exts:
                candidate = os.path.join(folder, base + ext)
                if os.path.isfile(candidate):
                    return candidate

        def _iter_image_files() -> Iterable[Tuple[str, str]]:
            entries = sorted(os.listdir(folder))
            for name in entries:
                lower = name.lower()
                if any(lower.endswith(ext) for ext in exts):
                    yield name, lower

        # 1er passage : évite les "anchor"/"crop" si possible
        for name, lower in _iter_image_files():
            if any(tag in lower for tag in ("anchor", "crop")):
                continue
            return os.path.join(folder, name)

        # 2e passage : prend la première image trouvée
        for name, _lower in _iter_image_files():
            return os.path.join(folder, name)

        return None

    @staticmethod
    def _default_table_capture(width: int, height: int) -> Dict[str, Any]:
        w = max(0, int(width))
        h = max(0, int(height))
        return {
            "enabled": True,
            "bounds": [0, 0, w, h],
            "origin": [0, 0],
            "size": [w, h],
        }

    @staticmethod
    def _normalise_table_capture(
        raw: Optional[Mapping[str, Any]],
        width: int,
        height: int,
    ) -> Dict[str, Any]:
        base = ZoneProject._default_table_capture(width, height)
        payload: Mapping[str, Any]
        payload = raw if isinstance(raw, Mapping) else {}

        result: Dict[str, Any] = dict(base)
        for key, value in payload.items():
            if key == "relative_bounds":
                continue
            result[key] = value

        def _as_pair(value: Any) -> Optional[Tuple[int, int]]:
            if isinstance(value, Iterable):
                values = list(value)
            else:
                return None
            if not values:
                return None
            x = coerce_int(values[0])
            y = coerce_int(values[1]) if len(values) >= 2 else 0
            return x, y

        def _as_bounds(value: Any) -> Optional[List[int]]:
            if isinstance(value, Iterable):
                values = list(value)
            else:
                return None
            if len(values) < 4:
                return None
            x1 = coerce_int(values[0])
            y1 = coerce_int(values[1])
            x2 = coerce_int(values[2])
            y2 = coerce_int(values[3])
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            return [x1, y1, x2, y2]

        bounds = _as_bounds(result.get("bounds"))
        if bounds is None and isinstance(payload, Mapping):
            rel = payload.get("relative_bounds")
            if isinstance(rel, Iterable):
                rel_vals = list(rel)
            else:
                rel_vals = []
            if len(rel_vals) >= 4:
                x = coerce_int(rel_vals[0])
                y = coerce_int(rel_vals[1])
                w = max(0, coerce_int(rel_vals[2]))
                h = max(0, coerce_int(rel_vals[3]))
                bounds = [x, y, x + w, y + h]
        if bounds is None:
            origin = _as_pair(result.get("origin"))
            size = _as_pair(result.get("size"))
            if origin and size:
                ox, oy = origin
                sw = max(0, size[0])
                sh = max(0, size[1])
                bounds = [ox, oy, ox + sw, oy + sh]
        if bounds is None:
            bounds = base["bounds"]
        result["bounds"] = bounds

        origin = _as_pair(result.get("origin"))
        if origin is None:
            origin = (bounds[0], bounds[1])
        result["origin"] = [origin[0], origin[1]]

        size = _as_pair(result.get("size"))
        if size is None:
            size = (max(0, bounds[2] - bounds[0]), max(0, bounds[3] - bounds[1]))
        result["size"] = [max(0, size[0]), max(0, size[1])]

        ref_offset = _as_pair(result.get("ref_offset"))
        if ref_offset is not None:
            result["ref_offset"] = [ref_offset[0], ref_offset[1]]
        elif "ref_offset" in result:
            del result["ref_offset"]

        result["enabled"] = bool(result.get("enabled", True))
        return result

    @staticmethod
    def list_games(base_dir: str) -> List[str]:
        """Retourne la liste des jeux (dossiers avec au moins une image)."""
        games: List[str] = []
        for name in sorted(os.listdir(base_dir)):
            full = os.path.join(base_dir, name)
            if os.path.isdir(full) and ZoneProject._find_expected_image(full):
                games.append(name)
        return games

    # ---------- Chargement ----------
    def load_game(self, base_dir: str, game_name: str) -> None:
        """Charge un jeu : image + coordinates.json.

        Ici on ne "corrige" pas les positions à l'ouverture, on reprend le JSON tel quel.
        """
        self.base_dir = os.path.abspath(base_dir)
        self.current_game = game_name

        folder = os.path.join(self.base_dir, game_name)
        img_path = ZoneProject._find_expected_image(folder)
        coord_path = os.path.join(folder, "coordinates.json")

        if not img_path or not os.path.isfile(img_path):
            raise FileNotFoundError(f"Image introuvable: {img_path or folder}")

        self.image_path = img_path
        self.image = Image.open(img_path).convert("RGBA")
        W, H = self.image_size

        # Réinit capture / templates / regions depuis le fichier
        self.table_capture = self._default_table_capture(W, H)
        self.templates = {}
        self.regions = OrderedDict()

        if os.path.isfile(coord_path):
            data = _load_templated_json(coord_path)
            self.table_capture = self._normalise_table_capture(
                data.get("table_capture"), W, H
            )
            self.templates.update(data.get("templates", {}))
            regs = data.get("regions", {})
            for key, r in regs.items():
                group = r.get("group", "")
                # *** PAS DE VALEUR PAR DÉFAUT ***
                tl = r["top_left"]
                self.regions[key] = {
                    "group": group,
                    "top_left": [coerce_int(tl[0]), coerce_int(tl[1])],
                    "value": r.get("value"),
                    "label": r.get("label", key),
                }
            # IMPORTANT : plus de _clamp_all() ici → on respecte le JSON
        else:
            # base minimale si pas de JSON
            self.templates.update(
                {"action_button": {"size": [165, 70], "type": "texte"}}
            )

        self._sync_game_capture()

    def _sync_game_capture(self) -> None:
        self.game.update_from_capture(
            table_capture=self.table_capture,
            regions=self.regions,
            templates=self.templates,
            reference_path=self.image_path,
        )

    # ---------- Opérations régions ----------
    def list_regions(self) -> List[str]:
        return list(self.regions.keys())

    def get_region(self, key: str) -> Dict[str, Any]:
        return self.regions[key]

    def rename_region(self, old_key: str, new_key: str) -> str:
        if new_key == old_key:
            return old_key
        if old_key not in self.regions:
            raise KeyError(f"Region inconnue: {old_key}")
        if new_key in self.regions:
            raise KeyError(f"Nouvelle clé déjà existante: {new_key}")
        r = self.regions.pop(old_key)
        r["label"] = new_key
        self.regions[new_key] = r
        return new_key

    def set_region_group(self, key: str, group: str) -> None:
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")
        if group not in self.templates:
            # crée un groupe par défaut si inconnu
            self.templates[group] = {"size": [60, 40], "type": "mix"}
        self.regions[key]["group"] = group
        self._clamp_region(key)

    def set_region_pos(self, key: str, x: int, y: int) -> None:
        """Déplace une région. Si lock_same_y, aligne Y de toutes les régions du groupe."""
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")

        g = self.regions[key]["group"]
        gw, gh = self.get_group_size(g)
        W, H = self.image_size

        # clamp et pose la région cible
        x, y = clamp_top_left(x, y, gw, gh, W, H)
        self.regions[key]["top_left"] = [x, y]

        # si contrainte d'alignement, propage Y
        if self.group_has_lock_same_y(g):
            self._enforce_lock_same_y(g, anchor_y=y)

    def add_region(self, group: str, name: Optional[str] = None) -> str:
        if group not in self.templates:
            self.templates[group] = {"size": [60, 40], "type": "mix"}
        W, H = self.image_size
        gw, gh = self.get_group_size(group)
        x, y = clamp_top_left(W // 2 - gw // 2, H // 2 - gh // 2, gw, gh, W, H)
        base = name or f"{group}_"
        if not name:
            i = 1
            while f"{base}{i}" in self.regions:
                i += 1
            key = f"{base}{i}"
        else:
            key = name
            if key in self.regions:
                i = 2
                while f"{key}_{i}" in self.regions:
                    i += 1
                key = f"{key}_{i}"
        self.regions[key] = {
            "group": group,
            "top_left": [x, y],
            "value": None,
            "label": key,
        }
        return key

    def delete_region(self, key: str) -> None:
        if key in self.regions:
            self.regions.pop(key)

    # ---------- Opérations groupes ----------
    def set_group_size(self, group: str, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            raise ValueError("Taille de groupe invalide")
        base = self.templates.get(group, {"type": "mix"})
        base["size"] = [int(w), int(h)]
        self.templates[group] = base
        # re-clamp toutes les régions de ce groupe
        for k, r in self.regions.items():
            if r.get("group") == group:
                self._clamp_region(k)
        # si lock_same_y → réaligner le Y commun
        if self.group_has_lock_same_y(group):
            self._enforce_lock_same_y(group, anchor_y=None)

    # ---------- Sauvegarde ----------
    def export_payload(self) -> Dict[str, Any]:
        W, H = self.image_size
        tc = self._normalise_table_capture(self.table_capture, W, H)
        out: Dict[str, Any] = {
            "table_capture": tc,
            "templates": self.templates,
            "regions": {},
        }
        for key, r in self.regions.items():
            tl = r["top_left"]  # *** pas de fallback [0,0] ***
            out["regions"][key] = {
                "group": r.get("group", ""),
                "top_left": [int(tl[0]), int(tl[1])],
                "value": r.get("value", None),
                "label": r.get("label", key),
            }
        return out

    def save_to(self, path: str) -> None:
        payload = self.export_payload()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ---------- internes ----------
    def _clamp_all(self) -> None:
        for k in list(self.regions.keys()):
            self._clamp_region(k)

    def _clamp_region(self, key: str) -> None:
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")
        W, H = self.image_size
        g = self.regions[key]["group"]
        gw, gh = self.get_group_size(g)
        x, y = self.regions[key]["top_left"]  # *** pas de .get(...,[0,0]) ***
        x, y = clamp_top_left(coerce_int(x), coerce_int(y), gw, gh, W, H)
        self.regions[key]["top_left"] = [x, y]

    def _enforce_lock_same_y(self, group: str, anchor_y: Optional[int]) -> None:
        """
        Aligne toutes les régions du groupe sur un même Y:
        - si anchor_y est fourni → on l'utilise (puis clamp commun).
        - sinon → min des Y existants (puis clamp commun).
        Clamp du X conservé par région.
        """
        keys = [k for k, r in self.regions.items() if r.get("group") == group]
        if not keys:
            return

        gw, gh = self.get_group_size(group)
        W, H = self.image_size

        if anchor_y is None:
            current_ys = [coerce_int(self.regions[k]["top_left"][1], 0) for k in keys]
            target_y = min(current_ys) if current_ys else 0
        else:
            target_y = coerce_int(anchor_y, 0)

        target_y = max(0, min(target_y, max(0, H - gh)))

        for k in keys:
            x, _y = self.regions[k]["top_left"]
            x, y = clamp_top_left(coerce_int(x), target_y, gw, gh, W, H)
            self.regions[k]["top_left"] = [x, y]

```
### tests/conftest.py
```python
"""Test helpers and environment shims for pytest."""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from typing import Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _install_cv2_stub() -> None:
    """Provide a tiny cv2 stub when OpenCV is unavailable."""

    if "cv2" in sys.modules:
        # Respect an existing installation (or another stub injected earlier).
        return

    module = types.ModuleType("cv2")
    module.COLOR_RGB2BGR = 0
    module.COLOR_BGR2RGB = 1
    module.COLOR_RGB2GRAY = 2
    module.COLOR_BGR2GRAY = 3
    module.TM_CCOEFF_NORMED = 5
    module.TM_SQDIFF = 6
    module.TM_SQDIFF_NORMED = 7
    module.CAP_PROP_FPS = 5
    module.__version__ = "0.0-tests"

    def cvtColor(arr: np.ndarray, code: int) -> np.ndarray:
        array = np.asarray(arr)
        if code in (module.COLOR_RGB2BGR, module.COLOR_BGR2RGB):
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            return array[..., ::-1].copy()
        if code == module.COLOR_RGB2GRAY:
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            r = array[..., 0].astype(float)
            g = array[..., 1].astype(float)
            b = array[..., 2].astype(float)
            gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
            return gray.astype(array.dtype, copy=False)
        if code == module.COLOR_BGR2GRAY:
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            b = array[..., 0].astype(float)
            g = array[..., 1].astype(float)
            r = array[..., 2].astype(float)
            gray = 0.1140 * b + 0.5870 * g + 0.2989 * r
            return gray.astype(array.dtype, copy=False)
        raise NotImplementedError(f"Unsupported conversion code: {code}")

    def matchTemplate(image: np.ndarray, template: np.ndarray, method: int = module.TM_CCOEFF_NORMED) -> np.ndarray:
        img = np.asarray(image, dtype=float)
        tpl = np.asarray(template, dtype=float)
        ih, iw = img.shape[:2]
        th, tw = tpl.shape[:2]
        if ih < th or iw < tw:
            raise ValueError("Template must be smaller than image.")
        out_h = ih - th + 1
        out_w = iw - tw + 1
        result = np.zeros((out_h, out_w), dtype=float)
        tpl_mean = tpl.mean()
        tpl_norm = tpl - tpl_mean
        tpl_denom = math.sqrt(float(np.sum(tpl_norm ** 2))) or 1.0
        tpl_energy = float(np.sum(tpl ** 2)) or 1.0
        for y in range(out_h):
            for x in range(out_w):
                patch = img[y : y + th, x : x + tw]
                if method == module.TM_CCOEFF_NORMED:
                    patch_mean = patch.mean()
                    patch_norm = patch - patch_mean
                    denom = math.sqrt(float(np.sum(patch_norm ** 2))) * tpl_denom
                    denom = denom or 1.0
                    score = float(np.sum(patch_norm * tpl_norm)) / denom
                    result[y, x] = score
                elif method in (module.TM_SQDIFF, module.TM_SQDIFF_NORMED):
                    diff = patch - tpl
                    mse = float(np.mean(diff ** 2))
                    if method == module.TM_SQDIFF:
                        result[y, x] = mse
                    else:
                        norm = float(np.mean(patch ** 2) + tpl_energy)
                        norm = norm or 1.0
                        result[y, x] = mse / norm
                else:
                    raise NotImplementedError(f"Unsupported matchTemplate method: {method}")
        return result

    def minMaxLoc(arr: np.ndarray) -> Tuple[float, float, Tuple[int, int], Tuple[int, int]]:
        array = np.asarray(arr)
        min_idx = int(array.argmin())
        max_idx = int(array.argmax())
        min_val = float(array.flat[min_idx])
        max_val = float(array.flat[max_idx])
        if array.ndim == 2:
            height, width = array.shape
            min_loc = (min_idx % width, min_idx // width)
            max_loc = (max_idx % width, max_idx // width)
        else:
            min_loc = (0, 0)
            max_loc = (0, 0)
        return min_val, max_val, min_loc, max_loc

    class VideoCapture:
        def __init__(self, *_, **__):
            raise RuntimeError("cv2.VideoCapture is unavailable in the test stub.")

        def read(self):  # pragma: no cover - stub
            return False, None

        def release(self) -> None:  # pragma: no cover - stub
            return None

        def get(self, *_):  # pragma: no cover - stub
            return 0.0

    module.cvtColor = cvtColor
    module.matchTemplate = matchTemplate
    module.minMaxLoc = minMaxLoc
    module.VideoCapture = VideoCapture

    sys.modules["cv2"] = module


_install_cv2_stub()

```
### tests/test_buttons.py
```python
"""Tests for button state parsing."""
from __future__ import annotations

from objet.entities.buttons import Button, Buttons


def test_one_is_activate_is_false_when_all_buttons_disabled() -> None:
    buttons = Buttons(button=[Button(enabled=False), Button(enabled=False)])

    assert buttons.one_is_activate() is False


def test_one_is_activate_is_true_when_one_button_enabled() -> None:
    buttons = Buttons(button=[Button(enabled=False), Button(enabled=True)])

    assert buttons.one_is_activate() is True


def test_apply_scan_disables_unknown_button_text() -> None:
    button = Button(enabled=True, texte="paie 1.00", etat="paie", value=1.0)

    button.apply_scan("texte inconnu")

    assert button.is_activate() is False
    assert button.etat == ""
    assert button.value == 0.0


def test_min_value_ignores_disabled_buttons() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=False, value=0.5),
            Button(enabled=True, value=2.0),
        ]
    )

    assert buttons.min_value() == 2.0

```
### tests/test_cards_recognition.py
```python
"""Tests for the `objet.scanner.cards_recognition` module."""

from pathlib import Path
import sys
import types

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

pyautogui_stub = types.ModuleType("pyautogui")
pyautogui_stub.locate = lambda *_, **__: None
sys.modules.setdefault("pyautogui", pyautogui_stub)

from objet.scanner.cards_recognition import is_cover_me_cards


def test_cover_overlay_is_detected() -> None:
    """The debug cover image should be recognised as the overlay."""

    cover_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "PMU"
        / "debug"
        / "cover.PNG"
    )

    with Image.open(cover_path) as cover_image:
        assert is_cover_me_cards(cover_image, threshold=0.55) is True







if __name__ == "__main__":
    test_cover_overlay_is_detected()
```
### tests/test_decision.py
```python
"""Tests for the Decision service."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from objet.entities.card import Card, CardsState
from objet.services.decision import Decision


class DummyPlayer:
    def __init__(self, fond_amount: float) -> None:
        self.fond = SimpleNamespace(amount=fond_amount)
        self.fond_start_Party = fond_amount
        self.active_at_start = True
        self.etat = "play"

    def is_activate(self) -> bool:
        return True


class DummyPlayers:
    def __init__(self) -> None:
        self._players = [DummyPlayer(100.0), DummyPlayer(80.0)]
        self.nbr_player_active = len(self._players)
        self.nbr_player_start = len(self._players)

    def __len__(self) -> int:
        return len(self._players)

    def __getitem__(self, index: int) -> DummyPlayer:
        return self._players[index]

    def __iter__(self):
        return iter(self._players)


class DummyButtons:
    def __init__(self, *, min_value: float = 1.0, active: bool = True) -> None:
        self._min_value = min_value
        self._active = active

    def one_is_activate(self) -> bool:
        return self._active

    def min_value(self) -> float:
        return self._min_value


class DummyTable:
    def __init__(
        self,
        cards_state: CardsState,
        pot_amount: Optional[float] = 50.0,
        buttons: Optional[DummyButtons] = None,
    ) -> None:
        self.cards = cards_state
        self.players = DummyPlayers()
        self.pot = None if pot_amount is None else SimpleNamespace(amount=pot_amount)
        self.buttons = buttons if buttons is not None else DummyButtons()


class DummyGame:
    def __init__(
        self,
        cards_state: CardsState,
        *,
        pot_amount: Optional[float] = 50.0,
        buttons: Optional[DummyButtons] = None,
        new_party_detected: bool = False,
    ) -> None:
        self.cards = cards_state
        self.table = DummyTable(cards_state, pot_amount, buttons)
        self.new_party_detected = new_party_detected
        self.etat = SimpleNamespace(
            cards=cards_state,
            players=self.table.players,
            chance_win=None,
            chance_win_0=None,
            pot=pot_amount,
            montant_a_jouer=None,
            Call_max=0.0,
        )


def _cards_state(first: Optional[str], second: Optional[str]) -> CardsState:
    board = [Card() for _ in range(5)]
    me = [
        Card(formatted=first, poker_card=object() if first else None),
        Card(formatted=second, poker_card=object() if second else None),
    ]
    return CardsState(board=board, me=me)


def _game_with_cards(first: Optional[str], second: Optional[str]) -> DummyGame:
    return DummyGame(_cards_state(first, second))


def test_wait_when_hero_cards_missing() -> None:
    game = _game_with_cards("AS", None)
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "hero_cards_not_detected_yet"


def test_wait_when_new_party_is_pending_reset() -> None:
    game = DummyGame(_cards_state("AS", "KS"), new_party_detected=True)
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "new_party_pending_reset"


def test_wait_when_no_button_is_active() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(active=False))
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "WAIT"
    assert result.reason == "not_buttons"


def test_check_when_call_max_is_below_min_button_value() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 1.0
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CHECK"
    assert result.reason == "chance_win_below_fold_threshold"


def test_raise_when_call_max_is_high() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 3.0
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "RAISE"
    assert result.reason == "chance_win_between_thresholds"


def test_call_when_call_max_is_close_to_min_button_value() -> None:
    game = DummyGame(_cards_state("AS", "KS"), buttons=DummyButtons(min_value=2.0))
    game.etat.Call_max = 2.02
    decision = Decision()

    result = decision.decide(game)

    assert result.action == "CALL"
    assert result.reason == "chance_win_above_aggressive_threshold"

```
### tests/test_game.py
```python
"""Tests for Game chronology and new-hand detection."""
from __future__ import annotations

from objet.entities.card import Card, CardsState
from objet.services.game import Game


class SpyEtat:
    def __init__(self) -> None:
        self.update_called = False

    def update(self, **_) -> None:
        self.update_called = True


def _set_visible_cards(game: Game, *, hero_count: int, board_count: int) -> None:
    me = [Card(formatted="hero") if index < hero_count else Card() for index in range(2)]
    board = [Card(formatted="board") if index < board_count else Card() for index in range(5)]
    game.table.cards = CardsState(board=board, me=me)


def test_missing_pot_does_not_clear_last_valid_pot() -> None:
    game = Game()
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 10.0
    assert game._detect_new_party() is False

    game.table.pot.amount = None
    assert game._detect_new_party() is None

    assert game._last_pot_amount == 10.0
    assert game.new_party_detected is False


def test_pot_drop_without_card_reduction_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=3)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._last_pot_amount == 100.0


def test_preflop_pot_drop_detects_new_party_without_card_reduction() -> None:
    game = Game()
    game.street = "PREFLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is True

    assert game.new_party_detected is True
    assert game._last_pot_amount == 60.0


def test_noisy_pot_drop_is_discarded_when_pot_recovers() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 100.0
    _set_visible_cards(game, hero_count=2, board_count=3)

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False

    game.table.pot.amount = 105.0
    assert game._detect_new_party() is False

    assert game._last_pot_amount == 105.0

    game.table.pot.amount = 60.0
    assert game._detect_new_party() is False


def test_pot_drop_with_card_reduction_detects_new_party_immediately() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is True

    assert game.new_party_detected is True
    assert game.street == "PREFLOP"
    assert game._pending_new_party_cleanup is True


def test_empty_scan_pot_drop_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=0, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game._last_pot_amount == 80.0
    assert game.street == "FLOP"


def test_partial_hero_scan_pot_drop_does_not_detect_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=1, board_count=0)

    game.table.pot.amount = 5.0
    assert game._detect_new_party() is False

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game._last_pot_amount == 80.0
    assert game.street == "FLOP"


def test_street_does_not_regress_without_new_party() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 20.0
    _set_visible_cards(game, hero_count=2, board_count=0)

    game.table.pot.amount = 25.0
    assert game._detect_new_party() is False

    assert game.street == "FLOP"


def test_update_from_scan_skips_state_update_when_new_party_detected() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)
    game.table.pot.amount = 5.0
    game.etat = SpyEtat()

    assert game.update_from_scan() is True

    assert game.etat.update_called is False


def test_ack_new_party_resets_flags_and_street() -> None:
    game = Game()
    game.street = "FLOP"
    game._last_pot_amount = 80.0
    _set_visible_cards(game, hero_count=2, board_count=0)
    game.table.pot.amount = 5.0
    game.table.buttons[0].apply_scan("paie 1.00")
    game.table.players[0].fond.amount = 12.0
    game.table.players[0].fond_start_Party = 20.0
    game.table.players[0].etat = "fold"
    game.table.players[0].active_at_start = False

    assert game._detect_new_party() is True
    game.ack_new_party()

    assert game.new_party_detected is False
    assert game._pending_new_party_cleanup is False
    assert game.street == "IDLE"
    assert game.table.pot.amount is None
    assert game.table.buttons[0].is_activate() is False
    assert game.table.players[0].fond.amount is None
    assert game.table.players[0].fond_start_Party == 0
    assert game.table.players[0].etat == "play"
    assert game.table.players[0].active_at_start is True
    assert all(card.formatted is None for card in game.table.cards.me_cards())
    assert all(card.formatted is None for card in game.table.cards.board_cards())

```
### tests/test_logging_config.py
```python
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from objet.utils.logging_config import (
    BACKUP_COUNT,
    DEFAULT_LOG_FILE,
    MAX_LOG_BYTES,
    configure_logging,
    get_logger,
    session_log,
)


def test_configure_logging_creates_rotating_debug_file_and_info_console(tmp_path, capsys) -> None:
    app_logger = configure_logging(log_dir=tmp_path, force=True)
    logger = get_logger("tests")

    logger.debug("debug fichier_only cle=1")
    logger.info("info console cle=2")
    _flush_handlers(app_logger)

    app_log = tmp_path / DEFAULT_LOG_FILE
    assert app_log.exists()

    content = app_log.read_text(encoding="utf-8")
    assert "DEBUG debug fichier_only cle=1" in content
    assert "INFO info console cle=2" in content

    captured = capsys.readouterr()
    assert "info console cle=2" in captured.err
    assert "debug fichier_only cle=1" not in captured.err

    file_handlers = [handler for handler in app_logger.handlers if isinstance(handler, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].level == logging.DEBUG
    assert file_handlers[0].maxBytes == MAX_LOG_BYTES
    assert file_handlers[0].backupCount == BACKUP_COUNT

    console_handlers = [
        handler
        for handler in app_logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler)
    ]
    assert len(console_handlers) == 1
    assert console_handlers[0].level == logging.INFO


def test_session_log_contains_only_session_messages(tmp_path) -> None:
    app_logger = configure_logging(log_dir=tmp_path, force=True)
    logger = get_logger("tests.session")

    logger.info("hors_session avant=1")
    with session_log("operation", log_dir=tmp_path) as session_path:
        logger.debug("debug session step=1")
        logger.info("info session step=2")
    logger.info("hors_session apres=1")
    _flush_handlers(app_logger)

    content = session_path.read_text(encoding="utf-8")
    assert "DEBUG debug session step=1" in content
    assert "INFO info session step=2" in content
    assert "hors_session avant=1" not in content
    assert "hors_session apres=1" not in content


def _flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()

```