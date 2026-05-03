"""Gestion centralisée de l'état du jeu."""

from dataclasses import dataclass, field
from pathlib import Path
import random
from typing import Any, Dict, Mapping, Optional, Sequence

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
from pokereval.card import Card as PokerEvalCard

from objet.services.script_state import SCRIPT_STATE_USAGE, StatePortion

LOGGER = get_logger(__name__)
DEFAULT_MONTE_CARLO_SIMULATIONS = 2000
DEFAULT_TO_CALL = 0.02

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
    chance_win: Optional[float] = None
    pot: Optional[float] = None
    to_call: float = DEFAULT_TO_CALL
    equity_required: Optional[float] = None
    monte_carlo_simulations: int = DEFAULT_MONTE_CARLO_SIMULATIONS
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
        self.chance_win_0 = HandEvaluator.evaluate_hand(hero_cards, board_poker_cards)
        opponent_count = max(0, self.players.nbr_player_active)
        self.chance_win = _monte_carlo_equity(
            hero_cards=hero_cards,
            board_cards=board_poker_cards,
            opponent_count=opponent_count,
            simulations=self.monte_carlo_simulations,
        )
        LOGGER.debug(
            "CALCUL chance_win hero=%s board=%s adversaires=%s chance_1v1=%s equity_table=%s simulations=%s",
            [card.formatted for card in me_cards],
            [card.formatted for card in board_cards],
            opponent_count,
            self.chance_win_0,
            self.chance_win,
            self.monte_carlo_simulations,
        )
        
        return self.chance_win


    def _cal_EV(self, to_call: Optional[float] = None)-> float:
        P = self.chance_win
        Pot = self.pot
        C = self.to_call if to_call is None else to_call
        return P * (Pot + C) - C
        

    def _cal_max_call(self) -> None:
        P = self.chance_win
        Pot = self.pot
        if P >= 1:
            self.Call_max = float("inf")
        else:
            self.Call_max = (P * Pot) / (1.0 - P)
        # >0: call OK, <0: fold

    def _cal_equity_required(self) -> None:
        pot_final = self.pot + self.to_call
        self.equity_required = self.to_call / pot_final if pot_final > 0 else None

    
    def _cal(self):
        if self.cards.is_ready_for_cal() and self.pot is not None:
            self._cal_win_chances()
            self.ev = self._cal_EV()
            self._cal_max_call()
            self._cal_equity_required()
            self._calcul_montant_a_jouer()
            LOGGER.info(
                "CALCUL etat pot=%s to_call=%s equity_table=%s chance_1v1=%s ev=%s call_max=%s equity_min=%s montant=%s",
                self.pot,
                self.to_call,
                self.chance_win,
                self.chance_win_0,
                self.ev,
                self.Call_max,
                self.equity_required,
                self.montant_a_jouer,
            )
        else:
            LOGGER.debug("SKIP calcul raison=cartes_hero_incompletes_ou_pot_absent")
    
    
    def _calcul_montant_a_jouer(self) -> float:
        self.montant_a_jouer = self.Call_max
        return self.montant_a_jouer
    
    
    
    
    
    def update_players(self, players: Players) -> None:
        self.players = players
        self.players.cal_nbr_player_start()
        self.players.cal_nbr_player_active()


    def update_cards_state(self, cards_state: CardsState) -> None:
        """Met à jour l'état des cartes."""
        nbr_scan = 3 *2
        board_count = sum(1 for card in cards_state.board if card.formatted)
        if board_count in (0, 3, 4, 5):
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
        else:
            LOGGER.debug(
                "SKIP update board raison=nombre_cartes_incoherent count=%s board=%s",
                board_count,
                [card.formatted for card in cards_state.board],
            )
        
            
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

    def update(self, *, cards_state: CardsState, players: Players, pot: Optional[float], to_call: Optional[float] = None) -> None:
        self.update_cards_state(cards_state)
        self.update_players(players)
        self.pot = pot if pot else self.pot
        self.to_call = DEFAULT_TO_CALL if to_call is None else max(0.0, to_call)
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
    _hand_id: int = field(default=1, init=False, repr=False)
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
            to_call=self._current_to_call(),
        )
        LOGGER.info(
            "ETAT stable hand=%s street=%s hero=%s board=%s pot=%s raw_hero=%s raw_board=%s joueurs=%s/%s",
            self._hand_id,
            self.street,
            [card.formatted for card in self.etat.cards.me_cards()],
            [card.formatted for card in self.etat.cards.board_cards()],
            self.etat.pot,
            sum(1 for card in self.table.cards.me_cards() if getattr(card, "formatted", None)),
            sum(1 for card in self.table.cards.board_cards() if getattr(card, "formatted", None)),
            self.etat.players.nbr_player_active,
            self.etat.players.nbr_player_start,
        )
        LOGGER.info("fin update_game status=ok nouvelle_partie=%s hand=%s", party_state, self._hand_id)
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
            LOGGER.debug("NOUVELLE_PARTIE pending_cleanup=True hand=%s", self._hand_id)
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
            LOGGER.debug("INIT pot amount=%s street=%s hand=%s", current_pot, self.street, self._hand_id)
            return False

        if self.street == "IDLE" and observed_street == "PREFLOP":
            self._last_pot_amount = current_pot
            self._new_party_flag = False
            self.street = observed_street
            LOGGER.info(
                "INIT main_depuis_idle hand=%s pot=%s cards=%s observed=%s",
                self._hand_id,
                current_pot,
                observed_card_count,
                observed_street,
            )
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
                self._hand_id += 1
                self._new_party_flag = True
                self._pending_new_party_cleanup = True
                self._last_pot_amount = current_pot
                if observed_street is not None:
                    self.street = observed_street
                LOGGER.info(
                    "NOUVELLE_PARTIE hand=%s pot=%s->%s cards=%s->%s street=%s observed=%s",
                    self._hand_id,
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

    def _current_to_call(self) -> float:
        buttons = getattr(self.table, "buttons", None)
        if buttons is None or not buttons.one_is_activate():
            return DEFAULT_TO_CALL
        return buttons.min_value()

    def ack_new_party(self) -> None:
        if not self._pending_new_party_cleanup:
            LOGGER.debug("SKIP ack_new_party raison=aucun_reset_en_attente")
            return
        LOGGER.info("debut reset_partie hand=%s street=%s pot=%s", self._hand_id, self.street, self._last_pot_amount)
        self.table.New_Party()
        self.etat.cards.reset()
        self.etat.players.reset()
        self.street = "IDLE"
        self._pending_new_party_cleanup = False
        self._new_party_flag = False
        LOGGER.info("fin reset_partie status=ok hand=%s street=%s", self._hand_id, self.street)

    @property
    def new_party_detected(self) -> bool:
        return self._new_party_flag

    @property
    def hand_id(self) -> int:
        return self._hand_id

    





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
   

def _monte_carlo_equity(
    *,
    hero_cards: Sequence[PokerEvalCard],
    board_cards: Sequence[PokerEvalCard],
    opponent_count: int,
    simulations: int,
) -> float:
    """Estimate hero equity versus active opponents by deterministic Monte Carlo."""

    if opponent_count <= 0:
        return 1.0

    missing_board_cards = 5 - len(board_cards)
    if missing_board_cards < 0:
        raise ValueError("Le board ne peut pas depasser 5 cartes.")

    known_cards = list(hero_cards) + list(board_cards)
    known_keys = {(card.rank, card.suit) for card in known_cards}
    deck = [
        PokerEvalCard(rank, suit)
        for rank in range(2, 15)
        for suit in range(1, 5)
        if (rank, suit) not in known_keys
    ]

    draw_count = opponent_count * 2 + missing_board_cards
    if draw_count > len(deck):
        raise ValueError("Pas assez de cartes restantes pour simuler la main.")

    rng = random.Random(_equity_seed(hero_cards, board_cards, opponent_count, simulations))
    runs = max(1, simulations)
    equity_total = 0.0

    for _ in range(runs):
        sample = rng.sample(deck, draw_count)
        opponent_cards = sample[: opponent_count * 2]
        completed_board = list(board_cards) + sample[opponent_count * 2 :]

        hero_rank = HandEvaluator.Seven.evaluate_rank(list(hero_cards) + completed_board)
        opponent_ranks = [
            HandEvaluator.Seven.evaluate_rank(
                opponent_cards[index * 2 : index * 2 + 2] + completed_board
            )
            for index in range(opponent_count)
        ]
        best_rank = min([hero_rank] + opponent_ranks)
        if hero_rank != best_rank:
            continue

        tied_opponents = sum(1 for rank in opponent_ranks if rank == best_rank)
        equity_total += 1.0 / (tied_opponents + 1)

    return equity_total / runs


def _equity_seed(
    hero_cards: Sequence[PokerEvalCard],
    board_cards: Sequence[PokerEvalCard],
    opponent_count: int,
    simulations: int,
) -> str:
    cards = list(hero_cards) + list(board_cards)
    encoded_cards = "-".join(f"{card.rank}:{card.suit}" for card in cards)
    return f"{encoded_cards}|opp={opponent_count}|sim={simulations}"


__all__ = [
    "Game",
    "CardObservation",
    "CardsState",
    "Buttons",
    "CaptureState",
]
