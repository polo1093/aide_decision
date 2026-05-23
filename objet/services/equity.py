"""Weighted equity simulation helpers.

The base simulator in ``game.py`` samples unknown cards uniformly.  This module
adds opponent profiles and combo weights while keeping the same deterministic
Monte Carlo style.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import json
from functools import lru_cache
from pathlib import Path
import random
from typing import Iterable, Optional, Sequence

from pokereval.card import Card as PokerEvalCard
from pokereval.hand_evaluator import HandEvaluator

from objet.services.pokerstove_ranges import (
    RangeStringError,
    cached_string_to_combos,
    combo_key as pokerstove_combo_key,
)


CardKey = tuple[int, int]
Combo = tuple[PokerEvalCard, PokerEvalCard]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
POKERMASTER_PREFLOP_EQUITY_PATH = PROJECT_ROOT / "Poker-master" / "poker" / "decisionmaker" / "preflop_equity.json"
RANK_TO_PREFLOP_NOTATION = {
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "T",
    11: "J",
    12: "Q",
    13: "K",
    14: "A",
}
UNKNOWN_PLAYER_RANGE = (
    "22+, A2s+, K8s+, Q9s+, J9s+, T8s+, 98s, 87s, 76s, 65s, "
    "A9o+, KTo+, QJo, JTo"
)
LOOSE_PLAYER_RANGE = (
    "22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 85s+, 75s+, 64s+, 54s, "
    "A2o+, K8o+, Q9o+, J9o+, T9o, 98o, 87o"
)
TIGHT_PLAYER_RANGE = "55+, A8s+, KTs+, QTs+, JTs, T9s, ATo+, KQo"
CALLING_RANGE = (
    "22-QQ, A2s-AQs, K9s+, QTs+, JTs, T9s, 98s, 87s, 76s, "
    "ATo-AQo, KJo+, QJo"
)
RAISING_RANGE = "77+, ATs+, KQs, AJo+, KQo, 50%(A5s-A2s, KJs, QJs, T9s)"
STRONG_RAISING_RANGE = "TT+, AQs+, AKo, 50%(99, AJs, AQo, KQs)"


@dataclass(frozen=True)
class OpponentProfile:
    """Compact opponent model used to weight preflop hand combinations.

    ``looseness`` describes how many starting hands remain plausible.
    ``aggression`` raises the weight of strong hands after observed pressure.
    Both values are clamped to ``0..1`` by the weighting functions.
    """

    name: str = "opponent"
    looseness: float = 0.55
    aggression: float = 0.35
    action: str = "play"
    confidence: float = 0.0
    range_string: Optional[str] = None


@dataclass(frozen=True)
class WeightedCombo:
    cards: Combo
    weight: float


@dataclass(frozen=True)
class WeightedComboRange:
    combos: tuple[WeightedCombo, ...]
    cumulative_weights: tuple[float, ...]
    total_weight: float


def opponent_profiles_from_players(players: Iterable[object]) -> list[OpponentProfile]:
    """Build active opponent profiles from the observed player state."""

    profiles: list[OpponentProfile] = []
    for index, player in enumerate(players, start=1):
        is_active = getattr(player, "is_activate", None)
        if callable(is_active) and not is_active():
            continue

        action = str(getattr(player, "etat", "play") or "play").lower()
        name = str(getattr(player, "name", "") or f"J{index}")

        looseness = 0.55
        aggression = 0.35

        if action in {"paid", "call", "paie"}:
            looseness = 0.36
            aggression = 0.68
        elif action in {"raise", "relance", "mise", "all-in"}:
            looseness = 0.24
            aggression = 0.92
        elif action in {"check", "play"}:
            looseness = 0.58
            aggression = 0.32

        if bool(getattr(player, "etat_modified_this_round", False)):
            aggression += 0.08

        start_amount = _as_float(getattr(player, "fond_start_Party", None))
        current_amount = _as_float(getattr(getattr(player, "fond", None), "amount", None))
        if start_amount and current_amount is not None and current_amount < start_amount:
            invested_ratio = min(1.0, max(0.0, (start_amount - current_amount) / start_amount))
            aggression += 0.18 * invested_ratio
            looseness -= 0.10 * invested_ratio

        profiles.append(
            OpponentProfile(
                name=name,
                looseness=_clamp01(looseness),
                aggression=_clamp01(aggression),
                action=action,
            )
        )

    return profiles


def profiles_for_opponent_count(
    profiles: Sequence[OpponentProfile],
    opponent_count: int,
) -> list[OpponentProfile]:
    """Return exactly ``opponent_count`` profiles, padding with defaults."""

    count = max(0, int(opponent_count))
    out = list(profiles[:count])
    while len(out) < count:
        out.append(OpponentProfile(name=f"opponent_{len(out) + 1}"))
    return out


def starting_hand_strength(cards: Sequence[PokerEvalCard]) -> Optional[float]:
    """Return normalized preflop strength for exactly two known cards."""

    if len(cards) != 2 or any(card is None for card in cards):
        return None
    if any(not hasattr(card, "rank") or not hasattr(card, "suit") for card in cards):
        return None
    return _starting_hand_strength((cards[0], cards[1]))


def weighted_monte_carlo_equity(
    *,
    hero_cards: Sequence[PokerEvalCard],
    board_cards: Sequence[PokerEvalCard],
    opponent_profiles: Sequence[OpponentProfile],
    simulations: int,
) -> float:
    """Estimate hero equity against weighted opponent ranges."""

    opponent_count = len(opponent_profiles)
    if opponent_count <= 0:
        return 1.0

    missing_board_cards = 5 - len(board_cards)
    if missing_board_cards < 0:
        raise ValueError("Le board ne peut pas depasser 5 cartes.")

    known_cards = list(hero_cards) + list(board_cards)
    known_keys = {_card_key(card) for card in known_cards}
    deck = [
        PokerEvalCard(rank, suit)
        for rank in range(2, 15)
        for suit in range(1, 5)
        if (rank, suit) not in known_keys
    ]

    draw_count = opponent_count * 2 + missing_board_cards
    if draw_count > len(deck):
        raise ValueError("Pas assez de cartes restantes pour simuler la main.")

    weighted_ranges = [
        _weighted_combo_range_for_profile(deck, profile)
        for profile in opponent_profiles
    ]
    rng = random.Random(_weighted_equity_seed(hero_cards, board_cards, opponent_profiles, simulations))
    runs = max(1, int(simulations))
    equity_total = 0.0

    for _ in range(runs):
        available_keys = {_card_key(card) for card in deck}
        opponent_hands: list[Combo] = []

        for weighted_range in weighted_ranges:
            combo = _choose_available_combo(weighted_range, available_keys, rng)
            opponent_hands.append(combo)
            available_keys.remove(_card_key(combo[0]))
            available_keys.remove(_card_key(combo[1]))

        remaining_deck = [card for card in deck if _card_key(card) in available_keys]
        completed_board = list(board_cards) + rng.sample(remaining_deck, missing_board_cards)

        hero_rank = HandEvaluator.Seven.evaluate_rank(list(hero_cards) + completed_board)
        opponent_ranks = [
            HandEvaluator.Seven.evaluate_rank(list(hand) + completed_board)
            for hand in opponent_hands
        ]
        best_rank = min([hero_rank] + opponent_ranks)
        if hero_rank != best_rank:
            continue

        tied_opponents = sum(1 for rank in opponent_ranks if rank == best_rank)
        equity_total += 1.0 / (tied_opponents + 1)

    return equity_total / runs


def _weighted_combo_range_for_profile(deck: Sequence[PokerEvalCard], profile: OpponentProfile) -> WeightedComboRange:
    range_string = _profile_range_string(profile)
    if range_string:
        parsed = _weighted_combo_range_from_pokerstove_string(deck, profile, range_string)
        if parsed is not None:
            return parsed

    return _weighted_combo_range_from_full_deck(deck, profile)


def _weighted_combo_range_from_pokerstove_string(
    deck: Sequence[PokerEvalCard],
    profile: OpponentProfile,
    range_string: str,
) -> Optional[WeightedComboRange]:
    available_keys = {_card_key(card) for card in deck}
    combos: list[WeightedCombo] = []
    cumulative: list[float] = []
    total = 0.0
    collapsed: dict[tuple[tuple[int, int], tuple[int, int]], tuple[Combo, float]] = {}

    try:
        parsed_combos = cached_string_to_combos(range_string)
    except RangeStringError:
        return None

    for parsed in parsed_combos:
        left, right = parsed.cards
        if _card_key(left) not in available_keys or _card_key(right) not in available_keys:
            continue
        key = pokerstove_combo_key(parsed.cards)
        current_cards, current_weight = collapsed.get(key, (parsed.cards, 0.0))
        collapsed[key] = (current_cards, current_weight + parsed.weight)

    for combo, range_weight in collapsed.values():
        weight = max(0.000001, float(range_weight) * _combo_weight(combo, profile))
        combos.append(WeightedCombo(combo, weight))
        total += weight
        cumulative.append(total)

    if not combos or total <= 0:
        return None
    return WeightedComboRange(tuple(combos), tuple(cumulative), total)


def _weighted_combo_range_from_full_deck(deck: Sequence[PokerEvalCard], profile: OpponentProfile) -> WeightedComboRange:
    combos: list[WeightedCombo] = []
    cumulative: list[float] = []
    total = 0.0
    for left_index, left in enumerate(deck):
        for right in deck[left_index + 1 :]:
            combo = (left, right)
            weighted = WeightedCombo(combo, _combo_weight(combo, profile))
            combos.append(weighted)
            total += weighted.weight
            cumulative.append(total)
    return WeightedComboRange(tuple(combos), tuple(cumulative), total)


def _profile_range_string(profile: OpponentProfile) -> Optional[str]:
    if profile.range_string:
        return profile.range_string

    action = str(profile.action or "play").lower()
    looseness = _clamp01(profile.looseness)

    if action in {"raise", "relance", "mise", "all-in"}:
        return STRONG_RAISING_RANGE if looseness <= 0.30 else RAISING_RANGE
    if action in {"paid", "call", "paie"}:
        return CALLING_RANGE
    if looseness >= 0.72:
        return LOOSE_PLAYER_RANGE
    if looseness <= 0.35:
        return TIGHT_PLAYER_RANGE
    return UNKNOWN_PLAYER_RANGE


def _choose_available_combo(
    weighted_range: WeightedComboRange,
    available_keys: set[CardKey],
    rng: random.Random,
) -> Combo:
    for _ in range(80):
        pick = rng.random() * weighted_range.total_weight
        index = min(
            len(weighted_range.combos) - 1,
            bisect_left(weighted_range.cumulative_weights, pick),
        )
        combo = weighted_range.combos[index].cards
        left, right = combo
        if _card_key(left) in available_keys and _card_key(right) in available_keys:
            return combo

    total = 0.0
    candidates: list[WeightedCombo] = []
    for weighted in weighted_range.combos:
        left, right = weighted.cards
        if _card_key(left) not in available_keys or _card_key(right) not in available_keys:
            continue
        candidates.append(weighted)
        total += weighted.weight

    if not candidates or total <= 0:
        raise ValueError("Pas assez de combos adverses disponibles pour simuler la main.")

    pick = rng.random() * total
    cursor = 0.0
    for weighted in candidates:
        cursor += weighted.weight
        if cursor >= pick:
            return weighted.cards
    return candidates[-1].cards


def _combo_weight(combo: Combo, profile: OpponentProfile) -> float:
    strength = _starting_hand_strength(combo)
    looseness = _clamp01(profile.looseness)
    aggression = _clamp01(profile.aggression)
    action = str(profile.action or "play").lower()

    selectivity = 3.2 - 2.35 * looseness
    weight = 0.04 + strength**selectivity

    if action in {"paid", "call", "paie"}:
        weight *= 0.28 + 1.75 * strength
    elif action in {"raise", "relance", "mise", "all-in"}:
        weight *= 0.10 + 2.75 * (strength**1.45)
    elif action in {"check"}:
        weight *= 1.10 - 0.25 * aggression

    if strength >= 0.68:
        weight *= 0.85 + 0.55 * aggression
    else:
        weight *= 1.12 - 0.22 * aggression

    return max(0.000001, float(weight))


def _starting_hand_strength(combo: Combo) -> float:
    ranked_strength = _pokermaster_preflop_strength(combo)
    if ranked_strength is not None:
        return ranked_strength

    left, right = combo
    ranks = sorted((int(left.rank), int(right.rank)), reverse=True)
    high, low = ranks
    suited = int(left.suit) == int(right.suit)

    if high == low:
        return _clamp01(0.44 + ((high - 2) / 12) * 0.52)

    high_score = ((high - 2) / 12) * 0.34
    low_score = ((low - 2) / 12) * 0.18
    gap = max(0, high - low - 1)
    connected = max(0.0, 0.13 - 0.026 * gap)
    suited_bonus = 0.08 if suited else 0.0
    broadway_bonus = 0.12 if low >= 10 else 0.0
    ace_bonus = 0.06 if high == 14 else 0.0

    return _clamp01(0.05 + high_score + low_score + connected + suited_bonus + broadway_bonus + ace_bonus)


def _pokermaster_preflop_strength(combo: Combo) -> Optional[float]:
    ranking = _load_pokermaster_preflop_ranking()
    if not ranking:
        return None

    key = _pokermaster_preflop_key(combo)
    equity = ranking.get(key)
    if equity is None:
        return None

    min_equity = min(ranking.values())
    max_equity = max(ranking.values())
    if max_equity <= min_equity:
        return None
    return _clamp01((equity - min_equity) / (max_equity - min_equity))


def _pokermaster_preflop_key(combo: Combo) -> str:
    left, right = combo
    ranks = sorted((int(left.rank), int(right.rank)))
    low, high = ranks
    low_label = RANK_TO_PREFLOP_NOTATION[low]
    high_label = RANK_TO_PREFLOP_NOTATION[high]
    if low == high:
        return f"{low_label}{high_label}"
    suited = "S" if int(left.suit) == int(right.suit) else "O"
    return f"{low_label}{high_label}{suited}"


@lru_cache(maxsize=1)
def _load_pokermaster_preflop_ranking() -> dict[str, float]:
    try:
        with POKERMASTER_PREFLOP_EQUITY_PATH.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError:
        return {}
    if not isinstance(raw, dict):
        return {}

    ranking: dict[str, float] = {}
    for key, value in raw.items():
        try:
            ranking[str(key).upper()] = float(value)
        except (TypeError, ValueError):
            continue
    return ranking


def _weighted_equity_seed(
    hero_cards: Sequence[PokerEvalCard],
    board_cards: Sequence[PokerEvalCard],
    profiles: Sequence[OpponentProfile],
    simulations: int,
) -> str:
    cards = list(hero_cards) + list(board_cards)
    encoded_cards = "-".join(f"{card.rank}:{card.suit}" for card in cards)
    encoded_profiles = "|".join(
        f"{profile.name}:{profile.action}:{profile.looseness:.3f}:{profile.aggression:.3f}"
        for profile in profiles
    )
    return f"{encoded_cards}|profiles={encoded_profiles}|sim={simulations}"


def _card_key(card: PokerEvalCard) -> CardKey:
    return int(card.rank), int(card.suit)


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = [
    "OpponentProfile",
    "WeightedCombo",
    "POKERMASTER_PREFLOP_EQUITY_PATH",
    "opponent_profiles_from_players",
    "profiles_for_opponent_count",
    "starting_hand_strength",
    "weighted_monte_carlo_equity",
]
