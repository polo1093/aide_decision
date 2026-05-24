"""Decision helper to recommend a poker action for the hero."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from objet.services.equity import starting_hand_strength
from objet.services.poker_charts import (
    DEFAULT_PROVIDER as POKER_CHARTS_DEFAULT_PROVIDER,
    PokerChartAction,
    get_cards_action as get_poker_charts_cards_action,
    normalize_provider as normalize_poker_charts_provider,
    normalize_scenario as normalize_poker_charts_scenario,
)
from objet.services.range_analyzer import RangeAction, classify_hole_cards, get_hand_action, normalize_position
from objet.services.decision_state import (
    ActionType,
    ButtonState,
    DecisionInput,
    DecisionOutput,
    HeroPositionInfo,
)
from objet.utils.logging_config import get_logger
from pokereval.card import Card as PokerEvalCard

DecisionMode = Literal["legacy", "pokermaster"]
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class DecisionResult(DecisionOutput):
    """Backward-compatible name for decision engine output."""



@dataclass(frozen=True)
class DecisionConfig:
    """Runtime configuration for the decision engine."""

    mode: DecisionMode = "legacy"


@dataclass(frozen=True)
class _DecisionContext:
    """Values derived once from the table state and shared by decision branches."""

    buttons: object
    free_action: bool
    aggressive_action: bool
    to_call: float
    equity: Optional[float]
    equity_required: Optional[float]
    call_max: float


class Decision:
    """Simple, fail-fast decision engine for the hero."""

    # Monte Carlo has variance, so a tiny positive edge is not enough to raise.
    FOLD_EDGE: float = -0.03
    RAISE_EDGE: float = 0.08
    PAID_RAISE_EDGE: float = 0.22
    FREE_RAISE_EQUITY: float = 0.65
    FREE_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.70,
        "FLOP": 0.72,
        "TURN": 0.76,
        "RIVER": 0.82,
    }
    PAID_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.78,
        "FLOP": 0.80,
        "TURN": 0.84,
        "RIVER": 0.90,
    }
    SMALL_BET_MAX_POT_RATIO: float = 0.25
    SMALL_BET_RAISE_EDGE: float = 0.18
    SMALL_BET_RAISE_EQUITY_BY_STREET = {
        "FLOP": 0.54,
        "TURN": 0.58,
    }
    RIVER_BIG_BET_MIN_POT_RATIO: float = 0.55
    RIVER_BIG_BET_MIN_1V1_EQUITY: float = 0.62

    POKERMASTER_FREE_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.74,
        "FLOP": 0.74,
        "TURN": 0.78,
        "RIVER": 0.84,
    }
    POKERMASTER_PAID_RAISE_EQUITY_BY_STREET = {
        "PREFLOP": 0.82,
        "FLOP": 0.84,
        "TURN": 0.88,
        "RIVER": 0.94,
    }
    POKERMASTER_PAID_RAISE_EDGE: float = 0.24
    POKERMASTER_RIVER_PRESSURE_POT_RATIO: float = 0.62
    POKERMASTER_RIVER_PRESSURE_MIN_EQUITY: float = 0.72
    POKERMASTER_LATE_STAGE_MIN_CALL: float = 240.0
    POKERMASTER_LATE_STAGE_MIN_POT: float = 720.0
    POKERMASTER_PREFLOP_SHOVE_STRENGTH: float = 0.72
    POKERMASTER_PREFLOP_CALL_STRENGTH: float = 0.50
    POKERMASTER_POSTFLOP_PRESSURE_EQUITY_BY_STREET = {
        "FLOP": 0.54,
        "TURN": 0.60,
        "RIVER": 0.72,
    }
    RANGE_ANALYZER_DEFAULT_POSITION = "BTN"
    RANGE_ANALYZER_PREFLOP_OPEN_FREQUENCY: int = 50
    RANGE_ANALYZER_PREFLOP_STRONG_RAISE_FREQUENCY: int = 75
    PREFLOP_RANGE_MAX_CHEAP_CALL_POT_RATIO: float = 0.40
    PREFLOP_RANGE_MIN_CHEAP_CALL_ABSOLUTE: float = 20.0
    PREFLOP_SUSPICIOUS_CALL_POT_RATIO: float = 4.0

    def __init__(
        self,
        config: Optional[DecisionConfig] = None,
        *,
        mode: Optional[DecisionMode] = None,
    ) -> None:
        if config is not None and mode is not None:
            raise ValueError("Use either config or mode, not both.")
        if config is None:
            config = DecisionConfig(mode=mode or "legacy")
        if config.mode not in ("legacy", "pokermaster"):
            raise ValueError(f"Mode de decision inconnu: {config.mode!r}")
        self.config = config

    def decide(self, game) -> DecisionResult:
        """Return the recommended action for the hero based on the current runtime game."""
        return self.decide_input(decision_input_from_game(game))

    def decide_input(self, state: DecisionInput) -> DecisionResult:
        """Return the recommended action from a normalized decision state."""
        if state.new_party_detected:
            return _log_decision(DecisionResult(action="WAIT", reason="new_party_pending_reset"))

        if not _hero_cards_ready(state):
            return _log_decision(DecisionResult(action="WAIT", reason="hero_cards_not_detected_yet"))

        if not _buttons_have_active_action(state.buttons):
            return _log_decision(DecisionResult(action="WAIT", reason="not_buttons"))

        context = _build_decision_context(state)
        if self.config.mode == "legacy":
            legacy_preflop = self._decide_legacy_preflop(state, context=context)
            if legacy_preflop is not None:
                return _log_decision(legacy_preflop)

        if context.equity is None:
            return _log_decision(DecisionResult(action="WAIT", reason="equity_not_ready"))

        # No money to add: never CALL. Check weak/medium hands, raise strong ones.
        if context.to_call <= 0:
            if self.config.mode == "pokermaster":
                return self._decide_pokermaster_free_action(
                    state,
                    buttons=context.buttons,
                    equity=context.equity,
                    free_action=context.free_action,
                    aggressive_action=context.aggressive_action,
                )
            if (
                context.free_action
                and context.aggressive_action
                and context.equity >= self._free_raise_equity_threshold(state)
            ):
                return _log_decision(
                    DecisionResult(
                        action="RAISE",
                        reason="free_option_strong_equity",
                        raise_amount=_recommended_raise_amount(state, context.buttons),
                    )
                )
            if context.free_action:
                return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))
            if _has_explicit_active_buttons(context.buttons):
                return _log_decision(DecisionResult(action="WAIT", reason="call_amount_not_detected"))
            return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))

        if context.equity_required is None:
            return _log_decision(DecisionResult(action="WAIT", reason="equity_required_not_ready"))

        edge = context.equity - context.equity_required
        LOGGER.debug(
            "DECISION contexte equity=%s equity_required=%s edge=%s call_max=%s to_call=%s",
            context.equity,
            context.equity_required,
            edge,
            context.call_max,
            context.to_call,
        )

        if self._should_wait_on_suspicious_premium_preflop_call(state, to_call=context.to_call):
            return _log_decision(DecisionResult(action="WAIT", reason="preflop_premium_call_amount_suspicious"))

        if context.call_max < context.to_call or edge < self.FOLD_EDGE:
            return _log_decision(DecisionResult(action="FOLD", reason="negative_call_ev"))

        if self.config.mode == "pokermaster":
            return self._decide_pokermaster_paid_action(
                state,
                buttons=context.buttons,
                equity=context.equity,
                edge=edge,
                to_call=context.to_call,
                aggressive_action=context.aggressive_action,
            )

        if self._should_fold_river_board_only_hand(state, to_call=context.to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_board_only_big_bet"))

        if self._should_fold_river_big_bet_with_weak_showdown(state, to_call=context.to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_big_bet_weak_showdown"))

        if self._can_value_raise_paid_pot(state, equity=context.equity, edge=edge):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="positive_edge_raise",
                    raise_amount=_recommended_raise_amount(state, context.buttons),
                )
            )

        if self._can_raise_small_bet_for_value(state, equity=context.equity, edge=edge, to_call=context.to_call):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="small_bet_value_protection",
                    raise_amount=_recommended_raise_amount(state, context.buttons),
                )
            )
        
        return _log_decision(DecisionResult(action="CALL", reason="call_profitable_or_close"))

    def _decide_legacy_preflop(
        self,
        state: DecisionInput,
        *,
        context: _DecisionContext,
    ) -> Optional[DecisionResult]:
        if _game_street(state) != "PREFLOP":
            return None

        pokercharts_result = self._decide_pokercharts_preflop(
            state,
            buttons=context.buttons,
            free_action=context.free_action,
            aggressive_action=context.aggressive_action,
            to_call=context.to_call,
        )
        if pokercharts_result is not None:
            return pokercharts_result

        range_fallback = self._decide_range_analyzer_preflop_without_equity(
            state,
            buttons=context.buttons,
            free_action=context.free_action,
            aggressive_action=context.aggressive_action,
            to_call=context.to_call,
        )
        if range_fallback is None:
            return None
        if self._should_use_legacy_preflop_range_fallback(
            state,
            range_fallback=range_fallback,
            context=context,
        ):
            return range_fallback
        return None

    def _should_use_legacy_preflop_range_fallback(
        self,
        state: DecisionInput,
        *,
        range_fallback: DecisionResult,
        context: _DecisionContext,
    ) -> bool:
        if context.equity is None:
            return True
        if context.to_call > 0 and context.equity_required is None:
            return True
        if self._should_trust_cheap_preflop_range_action(
            state,
            range_fallback=range_fallback,
            to_call=context.to_call,
        ):
            return True
        if range_fallback.action != "RAISE":
            return False
        if context.to_call <= 0:
            return True
        return (
            context.call_max >= context.to_call
            and context.equity_required is not None
            and (context.equity - context.equity_required) >= self.FOLD_EDGE
        )

    def _decide_range_analyzer_preflop_without_equity(
        self,
        state: DecisionInput,
        *,
        buttons,
        free_action: bool,
        aggressive_action: bool,
        to_call: float,
    ) -> Optional[DecisionResult]:
        range_action = self._hero_range_action(state)
        if range_action is None:
            return None

        if to_call <= 0:
            if aggressive_action and range_action.raise_frequency >= self.RANGE_ANALYZER_PREFLOP_OPEN_FREQUENCY:
                return DecisionResult(
                    action="RAISE",
                    reason="range_analyzer_preflop_open",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            if free_action:
                return DecisionResult(action="CHECK", reason="range_analyzer_preflop_check")
            if _has_explicit_active_buttons(buttons):
                return DecisionResult(action="WAIT", reason="call_amount_not_detected")
            return DecisionResult(action="CHECK", reason="range_analyzer_preflop_check")

        if range_action.playable_frequency <= 0:
            return DecisionResult(action="FOLD", reason="range_analyzer_preflop_out_of_range")

        if (
            aggressive_action
            and range_action.raise_frequency >= self.RANGE_ANALYZER_PREFLOP_STRONG_RAISE_FREQUENCY
        ):
            return DecisionResult(
                action="RAISE",
                reason="range_analyzer_preflop_value_raise",
                raise_amount=_recommended_raise_amount(state, buttons),
            )

        return DecisionResult(action="CALL", reason="range_analyzer_preflop_continue")

    def _should_trust_cheap_preflop_range_action(
        self,
        state: DecisionInput,
        *,
        range_fallback: DecisionResult,
        to_call: float,
    ) -> bool:
        if _game_street(state) != "PREFLOP" or to_call <= 0:
            return False
        if range_fallback.action not in {"CALL", "RAISE"}:
            return False

        pot = _as_positive_float(state.pot)
        if pot is None:
            return False
        cheap_call_cap = max(
            self.PREFLOP_RANGE_MIN_CHEAP_CALL_ABSOLUTE,
            pot * self.PREFLOP_RANGE_MAX_CHEAP_CALL_POT_RATIO,
        )
        return to_call <= cheap_call_cap

    def _decide_pokercharts_preflop(
        self,
        state: DecisionInput,
        *,
        buttons,
        free_action: bool,
        aggressive_action: bool,
        to_call: float,
    ) -> Optional[DecisionResult]:
        chart_action = self._hero_pokercharts_action(state, to_call=to_call)
        if chart_action is None:
            return None

        if to_call <= 0:
            if aggressive_action and chart_action.aggressive_frequency >= 50:
                return DecisionResult(
                    action="RAISE",
                    reason="pokercharts_preflop_open",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            if free_action:
                return DecisionResult(action="CHECK", reason="pokercharts_preflop_check")
            return DecisionResult(action="WAIT", reason="call_amount_not_detected")

        if chart_action.continue_frequency < 50:
            return DecisionResult(action="FOLD", reason="pokercharts_preflop_fold")

        if aggressive_action and chart_action.aggressive_frequency >= 75:
            return DecisionResult(
                action="RAISE",
                reason="pokercharts_preflop_aggressive",
                raise_amount=_recommended_raise_amount(state, buttons),
            )

        return DecisionResult(action="CALL", reason="pokercharts_preflop_continue")

    def _decide_pokermaster_free_action(
        self,
        state: DecisionInput,
        *,
        buttons,
        equity: float,
        free_action: bool,
        aggressive_action: bool,
    ) -> DecisionResult:
        if (
            _game_street(state) == "PREFLOP"
            and aggressive_action
            and self._pokermaster_late_stage_pressure(state, to_call=0.0)
            and self._hero_preflop_strength(state) >= self.POKERMASTER_PREFLOP_SHOVE_STRENGTH
        ):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_short_stack_preflop_pressure",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            )

        if free_action and aggressive_action and equity >= self._pokermaster_free_raise_equity_threshold(state):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_free_value_raise",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            )
        if free_action:
            return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))
        if _has_explicit_active_buttons(buttons):
            return _log_decision(DecisionResult(action="WAIT", reason="call_amount_not_detected"))
        return _log_decision(DecisionResult(action="CHECK", reason="free_option_no_call_needed"))

    def _decide_pokermaster_paid_action(
        self,
        state: DecisionInput,
        *,
        buttons,
        equity: float,
        edge: float,
        to_call: float,
        aggressive_action: bool,
    ) -> DecisionResult:
        short_stack_preflop = self._decide_pokermaster_short_stack_preflop(
            state,
            buttons=buttons,
            to_call=to_call,
            aggressive_action=aggressive_action,
        )
        if short_stack_preflop is not None:
            return short_stack_preflop

        if self._pokermaster_should_fold_postflop_tournament_pressure(state, equity=equity, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_postflop_tournament_pressure"))

        if self._should_fold_river_board_only_hand(state, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_board_only_big_bet"))

        if self._should_fold_river_big_bet_with_weak_showdown(state, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="river_big_bet_weak_showdown"))

        if self._pokermaster_should_fold_river_pressure(state, equity=equity, to_call=to_call):
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_river_pressure"))

        if aggressive_action and self._can_pokermaster_value_raise_paid_pot(state, equity=equity, edge=edge):
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_paid_value_raise",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            )

        return _log_decision(DecisionResult(action="CALL", reason="call_profitable_or_close"))

    def _free_raise_equity_threshold(self, state: DecisionInput) -> float:
        street = _game_street(state)
        return self.FREE_RAISE_EQUITY_BY_STREET.get(street, self.FREE_RAISE_EQUITY)

    def _can_value_raise_paid_pot(self, state: DecisionInput, *, equity: float, edge: float) -> bool:
        if edge < max(self.RAISE_EDGE, self.PAID_RAISE_EDGE):
            return False
        street = _game_street(state)
        threshold = self.PAID_RAISE_EQUITY_BY_STREET.get(street, 0.84)
        return equity >= threshold

    def _can_pokermaster_value_raise_paid_pot(self, state: DecisionInput, *, equity: float, edge: float) -> bool:
        if edge < self.POKERMASTER_PAID_RAISE_EDGE:
            return False
        street = _game_street(state)
        threshold = self.POKERMASTER_PAID_RAISE_EQUITY_BY_STREET.get(street, 0.88)
        return equity >= threshold

    def _decide_pokermaster_short_stack_preflop(
        self,
        state: DecisionInput,
        *,
        buttons,
        to_call: float,
        aggressive_action: bool,
    ) -> Optional[DecisionResult]:
        if _game_street(state) != "PREFLOP" or not self._pokermaster_late_stage_pressure(state, to_call=to_call):
            return None

        strength = self._hero_preflop_strength(state)
        if aggressive_action and strength >= self.POKERMASTER_PREFLOP_SHOVE_STRENGTH:
            return _log_decision(
                DecisionResult(
                    action="RAISE",
                    reason="pokermaster_short_stack_preflop_pressure",
                    raise_amount=_recommended_raise_amount(state, buttons),
                )
            )

        if strength < self.POKERMASTER_PREFLOP_CALL_STRENGTH:
            return _log_decision(DecisionResult(action="FOLD", reason="pokermaster_short_stack_preflop_fold"))

        return None

    def _can_raise_small_bet_for_value(
        self,
        state: DecisionInput,
        *,
        equity: float,
        edge: float,
        to_call: float,
    ) -> bool:
        street = _game_street(state)
        threshold = self.SMALL_BET_RAISE_EQUITY_BY_STREET.get(street)
        if threshold is None:
            return False
        if equity < threshold or edge < self.SMALL_BET_RAISE_EDGE:
            return False
        pot = _as_positive_float(state.pot)
        if pot is None:
            return False
        return (to_call / pot) <= self.SMALL_BET_MAX_POT_RATIO

    def _should_fold_river_board_only_hand(self, state: DecisionInput, *, to_call: float) -> bool:
        if _game_street(state) != "RIVER":
            return False
        pot = _as_positive_float(state.pot)
        if pot is None or pot <= 0 or (to_call / pot) < 0.65:
            return False
        return _hero_uses_no_private_card(state)

    def _should_fold_river_big_bet_with_weak_showdown(self, state: DecisionInput, *, to_call: float) -> bool:
        if _game_street(state) != "RIVER":
            return False
        pot = _as_positive_float(state.pot)
        if pot is None or (to_call / pot) < self.RIVER_BIG_BET_MIN_POT_RATIO:
            return False
        equity_1v1 = _as_probability(state.equity_1v1)
        if equity_1v1 is None:
            return False
        return equity_1v1 < self.RIVER_BIG_BET_MIN_1V1_EQUITY

    def _pokermaster_free_raise_equity_threshold(self, state: DecisionInput) -> float:
        street = _game_street(state)
        return self.POKERMASTER_FREE_RAISE_EQUITY_BY_STREET.get(street, 0.78)

    def _pokermaster_should_fold_river_pressure(self, state: DecisionInput, *, equity: float, to_call: float) -> bool:
        if _game_street(state) != "RIVER":
            return False
        pot = _as_positive_float(state.pot)
        if pot is None or pot <= 0:
            return False
        return (to_call / pot) >= self.POKERMASTER_RIVER_PRESSURE_POT_RATIO and equity < self.POKERMASTER_RIVER_PRESSURE_MIN_EQUITY

    def _pokermaster_should_fold_postflop_tournament_pressure(
        self,
        state: DecisionInput,
        *,
        equity: float,
        to_call: float,
    ) -> bool:
        street = _game_street(state)
        threshold = self.POKERMASTER_POSTFLOP_PRESSURE_EQUITY_BY_STREET.get(street)
        if threshold is None or not self._pokermaster_late_stage_pressure(state, to_call=to_call):
            return False
        pot = _as_positive_float(state.pot)
        if pot is None or pot <= 0:
            return False
        pressure_ratio = to_call / pot
        return pressure_ratio >= 0.22 and equity < threshold

    def _pokermaster_late_stage_pressure(self, state: DecisionInput, *, to_call: float) -> bool:
        pot = _as_positive_float(state.pot) or 0.0
        return to_call >= self.POKERMASTER_LATE_STAGE_MIN_CALL or pot >= self.POKERMASTER_LATE_STAGE_MIN_POT

    def _hero_preflop_strength(self, state: DecisionInput) -> float:
        hero_cards = _poker_cards_from_labels(_strategy_hero_cards(state))
        strength = starting_hand_strength(hero_cards)
        return 0.0 if strength is None else strength

    def _hero_range_action(self, state: DecisionInput) -> Optional[RangeAction]:
        hero_cards = _poker_cards_from_labels(_strategy_hero_cards(state))
        hand = classify_hole_cards(hero_cards)
        if hand is None:
            return None
        return get_hand_action(_range_analyzer_position(state), hand)

    def _hero_pokercharts_action(self, state: DecisionInput, *, to_call: float) -> Optional[PokerChartAction]:
        hero_cards = _poker_cards_from_labels(_strategy_hero_cards(state))
        scenario = "RFI" if to_call <= 0 else _pokercharts_scenario(state)
        if scenario is None:
            return None
        return get_poker_charts_cards_action(
            _pokercharts_provider(state),
            _range_analyzer_position(state),
            scenario,
            hero_cards,
            _pokercharts_villain_position(state),
        )

    def _should_wait_on_suspicious_premium_preflop_call(self, state: DecisionInput, *, to_call: float) -> bool:
        if _game_street(state) != "PREFLOP" or to_call <= 0:
            return False
        pot = _as_positive_float(state.pot)
        if pot is None or pot <= 0 or (to_call / pot) < self.PREFLOP_SUSPICIOUS_CALL_POT_RATIO:
            return False
        range_action = self._hero_range_action(state)
        if range_action is None:
            return False
        return range_action.raise_frequency >= self.RANGE_ANALYZER_PREFLOP_STRONG_RAISE_FREQUENCY


def _log_decision(result: DecisionResult) -> DecisionResult:
    LOGGER.info("DECISION action=%s reason=%s raise=%s", result.action, result.reason, result.raise_amount)
    return result


def _legacy_decision(game: Game) -> DecisionResult:
    return Decision(mode="legacy").decide(game)


def decision_input_from_game(game) -> DecisionInput:
    """Build a scanner-free decision DTO from the runtime Game object."""
    etat = getattr(game, "etat", None)
    table = getattr(game, "table", None)
    buttons = _button_states_from_buttons(getattr(table, "buttons", None))
    return DecisionInput(
        new_party_detected=bool(getattr(game, "new_party_detected", False)),
        street=_game_street(game),
        hero_cards=_card_labels(getattr(etat, "cards", None), "me_cards"),
        board_cards=_card_labels(getattr(etat, "cards", None), "board_cards"),
        strategy_hero_cards=_strategy_card_labels(getattr(etat, "cards", None), "me_cards"),
        buttons=buttons,
        pot=getattr(etat, "pot", None),
        to_call=_to_call_from_buttons(buttons),
        equity=getattr(etat, "chance_win", None),
        equity_1v1=getattr(etat, "chance_win_0", None),
        equity_required=getattr(etat, "equity_required", None),
        call_max=getattr(etat, "Call_max", 0.0),
        amount_to_play=getattr(etat, "montant_a_jouer", None),
        hero_position=HeroPositionInfo(
            position=_range_analyzer_position(game),
            reason=str(getattr(game, "hero_position_reason", "") or ""),
            confidence=getattr(game, "hero_position_confidence", None),
        ),
        pokercharts_provider=_pokercharts_provider_from_runtime(game),
        preflop_scenario=_pokercharts_scenario_from_runtime(game),
        villain_position=_pokercharts_villain_position_from_runtime(game),
    )


def _build_decision_context(state: DecisionInput) -> _DecisionContext:
    free_action = _free_action_available(state.buttons)
    to_call = 0.0 if free_action else state.to_call or _to_call_from_buttons(state.buttons)
    return _DecisionContext(
        buttons=state.buttons,
        free_action=free_action,
        aggressive_action=_aggressive_action_available(state.buttons),
        to_call=to_call,
        equity=state.equity,
        equity_required=state.equity_required,
        call_max=state.call_max,
    )


def _button_states_from_buttons(buttons) -> list[ButtonState]:
    states = [
        ButtonState(
            enabled=bool(getattr(button, "enabled", False)),
            state=str(getattr(button, "etat", "") or ""),
            value=float(getattr(button, "value", 0.0) or 0.0),
            text=str(getattr(button, "texte", "") or ""),
        )
        for button in _iter_buttons(buttons)
    ]
    if states:
        return states

    one_is_activate = getattr(buttons, "one_is_activate", None)
    if not callable(one_is_activate) or not one_is_activate():
        return []
    value = _as_positive_float(getattr(buttons, "min_value", lambda: 0.0)()) or 0.0
    return [ButtonState(enabled=True, state="check" if value <= 0 else "paie", value=value)]


def _card_labels(cards, method_name: str) -> list[Optional[str]]:
    method = getattr(cards, method_name, None)
    if not callable(method):
        return []
    return [getattr(card, "formatted", None) for card in method()]


def _strategy_card_labels(cards, method_name: str) -> list[Optional[str]]:
    method = getattr(cards, method_name, None)
    if not callable(method):
        return []
    return [
        getattr(card, "formatted", None)
        if isinstance(getattr(card, "poker_card", None), PokerEvalCard)
        else None
        for card in method()
    ]


def _hero_cards_ready(state: DecisionInput) -> bool:
    return len(state.hero_cards) >= 2 and all(_poker_card_from_label(card) is not None for card in state.hero_cards[:2])


def _buttons_have_active_action(buttons) -> bool:
    return any(getattr(button, "enabled", False) for button in _iter_buttons(buttons))


def _free_action_available(buttons) -> bool:
    has_free_action = getattr(buttons, "has_free_action", None)
    if callable(has_free_action):
        return bool(has_free_action())
    return any(
        getattr(button, "enabled", False) and getattr(button, "etat", "").lower() == "check"
        for button in _iter_buttons(buttons)
    )


def _aggressive_action_available(buttons) -> bool:
    has_aggressive_action = getattr(buttons, "has_aggressive_action", None)
    if callable(has_aggressive_action):
        return bool(has_aggressive_action())
    return any(
        getattr(button, "enabled", False) and getattr(button, "etat", "").lower() in {"mise", "relance", "all-in"}
        for button in _iter_buttons(buttons)
    )


def _has_explicit_active_buttons(buttons) -> bool:
    return any(getattr(button, "enabled", False) for button in _iter_buttons(buttons))


def _game_street(state) -> str:
    return str(getattr(state, "street", "") or "").upper()


def _range_analyzer_position(state) -> str:
    if isinstance(state, DecisionInput):
        position = normalize_position(state.hero_position.position)
        return position or Decision.RANGE_ANALYZER_DEFAULT_POSITION
    for source in (state, getattr(state, "etat", None), getattr(state, "table", None)):
        if source is None:
            continue
        for attr in ("range_position", "hero_position", "position"):
            position = normalize_position(getattr(source, attr, None))
            if position is not None:
                return position
    return Decision.RANGE_ANALYZER_DEFAULT_POSITION


def _pokercharts_provider(state: DecisionInput) -> str:
    return normalize_poker_charts_provider(state.pokercharts_provider) or POKER_CHARTS_DEFAULT_PROVIDER


def _pokercharts_provider_from_runtime(game) -> str:
    for source in (game, getattr(game, "etat", None), getattr(game, "table", None)):
        if source is None:
            continue
        for attr in ("pokercharts_provider", "poker_charts_provider", "range_provider"):
            provider = normalize_poker_charts_provider(getattr(source, attr, None))
            if provider is not None:
                return provider
    return POKER_CHARTS_DEFAULT_PROVIDER


def _pokercharts_scenario(state: DecisionInput) -> Optional[str]:
    return normalize_poker_charts_scenario(state.preflop_scenario)


def _pokercharts_scenario_from_runtime(game) -> Optional[str]:
    for source in (game, getattr(game, "etat", None), getattr(game, "table", None)):
        if source is None:
            continue
        for attr in ("preflop_scenario", "pokercharts_scenario", "range_scenario"):
            scenario = normalize_poker_charts_scenario(getattr(source, attr, None))
            if scenario is not None:
                return scenario
    return None


def _pokercharts_villain_position(state: DecisionInput) -> Optional[str]:
    return normalize_position(state.villain_position)


def _pokercharts_villain_position_from_runtime(game) -> Optional[str]:
    for source in (game, getattr(game, "etat", None), getattr(game, "table", None)):
        if source is None:
            continue
        for attr in ("villain_position", "opener_position", "aggressor_position"):
            position = normalize_position(getattr(source, attr, None))
            if position is not None:
                return position
    return None


def _recommended_raise_amount(state: DecisionInput, buttons) -> Optional[float]:
    pot = _as_positive_float(state.pot)
    to_call = _call_button_value(buttons)
    amount = _pot_sized_raise_amount(pot=pot, to_call=to_call, street=_game_street(state))
    if amount is None:
        amount = _as_positive_float(state.amount_to_play)
    if amount is None:
        amount = _as_positive_float(state.call_max)
    min_raise = _min_aggressive_button_value(buttons)
    if amount is None:
        return min_raise
    if min_raise is not None and not _looks_like_preset_button(min_raise, pot):
        amount = max(amount, min_raise)
    return _round_chip_amount(amount)


def _pot_sized_raise_amount(
    *,
    pot: Optional[float],
    to_call: float,
    street: str,
) -> Optional[float]:
    if pot is None or pot <= 0:
        return None
    if to_call > 0:
        ratio = 0.62 if street in {"FLOP", "TURN"} else 0.50
        return max(to_call * 3.0, pot * ratio)
    ratio_by_street = {
        "PREFLOP": 0.55,
        "FLOP": 0.66,
        "TURN": 0.66,
        "RIVER": 0.50,
    }
    return pot * ratio_by_street.get(street, 0.60)


def _call_button_value(buttons) -> float:
    min_value = getattr(buttons, "min_value", None)
    if callable(min_value):
        value = _as_positive_float(min_value())
        return value or 0.0
    return _to_call_from_buttons(buttons)


def _to_call_from_buttons(buttons) -> float:
    if _free_action_available(buttons):
        return 0.0
    values = [
        value
        for button in _iter_buttons(buttons)
        if getattr(button, "enabled", False)
        and str(getattr(button, "etat", "")).lower() == "paie"
        for value in [_as_positive_float(getattr(button, "value", None))]
        if value is not None
    ]
    return min(values) if values else 0.0


def _looks_like_preset_button(value: float, pot: Optional[float]) -> bool:
    return pot is not None and pot > 0 and value > pot * 2.5


def _round_chip_amount(amount: float) -> float:
    if amount >= 100:
        return float(round(amount / 20.0) * 20)
    if amount >= 20:
        return float(round(amount / 10.0) * 10)
    return float(round(amount, 2))


def _min_aggressive_button_value(buttons) -> Optional[float]:
    values = [
        value
        for button in _iter_buttons(buttons)
        if getattr(button, "enabled", False)
        and str(getattr(button, "etat", "")).lower() in {"mise", "relance", "all-in"}
        for value in [_as_positive_float(getattr(button, "value", None))]
        if value is not None
    ]
    return min(values) if values else None


def _as_positive_float(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _as_probability(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 <= number <= 1.0:
        return None
    return number


def _poker_cards_from_labels(labels: list[Optional[str]]) -> list[Optional[PokerEvalCard]]:
    return [_poker_card_from_label(label) for label in labels]


def _strategy_hero_cards(state: DecisionInput) -> list[Optional[str]]:
    return state.strategy_hero_cards or state.hero_cards


def _poker_card_from_label(label: Optional[str]) -> Optional[PokerEvalCard]:
    if not label:
        return None
    text = str(label).strip().upper()
    suit_aliases = {
        "S": 1,
        "\u2660": 1,
        "H": 2,
        "\u2665": 2,
        "D": 3,
        "\u2666": 3,
        "C": 4,
        "\u2663": 4,
    }
    value_aliases = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "9": 9,
        "10": 10,
        "T": 10,
        "J": 11,
        "Q": 12,
        "K": 13,
        "A": 14,
    }
    if len(text) < 2:
        return None
    value = value_aliases.get(text[:-1])
    suit = suit_aliases.get(text[-1])
    if value is None or suit is None:
        return None
    return PokerEvalCard(value, suit)


def _hero_uses_no_private_card(state: DecisionInput) -> bool:
    try:
        from pokereval.hand_evaluator import HandEvaluator
    except Exception:
        return False

    hero_cards = _poker_cards_from_labels(state.hero_cards)
    board_cards = [card for card in _poker_cards_from_labels(state.board_cards) if card is not None]
    if len(hero_cards) != 2 or len(board_cards) != 5:
        return False
    if any(card is None for card in [*hero_cards, *board_cards]):
        return False
    return HandEvaluator.Seven.evaluate_rank([*hero_cards, *board_cards]) == HandEvaluator.Five.evaluate_rank(board_cards)


def _iter_buttons(buttons):
    try:
        return iter(buttons)
    except TypeError:
        return iter(())


__all__ = [
    "ActionType",
    "ButtonState",
    "DecisionConfig",
    "DecisionInput",
    "DecisionOutput",
    "DecisionResult",
    "HeroPositionInfo",
    "Decision",
    "decision_input_from_game",
]
