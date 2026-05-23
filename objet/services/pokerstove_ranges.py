"""PokerStove-style range parsing helpers.

The parser is adapted from julianandrews/pyeval7's pure Python range parser
(MIT license).  It returns project-native ``pokereval`` cards so the rest of
the engine does not need eval7's Cython extensions.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import pyparsing
from pokereval.card import Card as PokerEvalCard


RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A")
SUITS = ("c", "d", "h", "s")
SUIT_TO_POKEREVAL = {
    "s": 1,
    "h": 2,
    "d": 3,
    "c": 4,
}
RANK_TO_POKEREVAL = {rank: index + 2 for index, rank in enumerate(RANKS)}


class RangeStringError(ValueError):
    """Raised when a range string cannot be parsed."""


@dataclass(frozen=True)
class ParsedCombo:
    cards: tuple[PokerEvalCard, PokerEvalCard]
    weight: float = 1.0


def string_to_tokens(range_string: str) -> list[tuple[str, float]]:
    """Parse a PokerStove-style range string into weighted hand tokens."""

    tokens: list[tuple[str, float]] = []
    try:
        results = _PARSER.parse_string(range_string)
    except pyparsing.ParseException as exc:
        raise RangeStringError("Failed to parse range string") from exc

    for result in results:
        if len(result) == 2:
            weight = weight_to_float(result[0])
            handtype_groups = result[1]
        else:
            weight = 1.0
            handtype_groups = result[0]
        for token in _flatten(expand_handtype_group(group) for group in handtype_groups):
            tokens.append((token, weight))
    return tokens


def string_to_combos(range_string: str) -> tuple[ParsedCombo, ...]:
    """Return concrete weighted two-card combos for ``range_string``."""

    combos: list[ParsedCombo] = []
    for token, weight in string_to_tokens(range_string):
        if token.startswith("#"):
            continue
        combos.extend(
            ParsedCombo((_card_from_string(left), _card_from_string(right)), weight)
            for left, right in token_to_hands(token)
        )
    return tuple(combos)


@lru_cache(maxsize=128)
def cached_string_to_combos(range_string: str) -> tuple[ParsedCombo, ...]:
    """Cached variant for equity simulations."""

    return string_to_combos(range_string)


def validate_string(range_string: str) -> bool:
    try:
        string_to_tokens(range_string)
    except RangeStringError:
        return False
    return True


def weight_to_float(weight_tokens: Iterable[str]) -> float:
    parts = list(weight_tokens)
    value = float(parts[0])
    if parts[-1] == "%":
        value /= 100.0
    return value


def expand_handtype_group(handtype_group) -> list[str]:
    """Expand one parsed group such as ``ATs+`` or ``55-99`` into tokens."""

    tokens: list[str] = []

    def sorted_ranks(token: str) -> list[int]:
        return sorted((RANKS.index(token[0]), RANKS.index(token[1])), reverse=True)

    if handtype_group[0] == "#":
        tokens = ["".join(handtype_group)]
    elif len(handtype_group) == 1:
        tokens = [normalize_token(handtype_group[0])]
    else:
        suitedness = token_suitedness(handtype_group[0])
        if handtype_group[-1] == "+":
            token = normalize_token(handtype_group[0])
            bottom = sorted_ranks(token)
            top = (12, 12) if suitedness == "p" else (bottom[0], bottom[0] - 1)
        elif handtype_group[1] == "-":
            if suitedness != token_suitedness(handtype_group[2]):
                raise RangeStringError(
                    "Suitedness mismatch: {!r} {!r}".format(handtype_group[0], handtype_group[2])
                )
            bottom = sorted_ranks(normalize_token(handtype_group[0]))
            top = sorted_ranks(normalize_token(handtype_group[2]))
            if top[1] < bottom[1]:
                bottom, top = top, bottom
        else:
            raise RangeStringError("Invalid hand type group: {!r}".format(handtype_group))

        if suitedness != "p" and top[0] != bottom[0]:
            raise RangeStringError(
                "Top card mismatch: {!r} {!r}".format(handtype_group[0], handtype_group[-1])
            )
        for index in range(bottom[1], top[1] + 1):
            rank_indexes = (index, index) if suitedness == "p" else (top[0], index)
            token = "".join(RANKS[rank_index] for rank_index in rank_indexes) + suitedness
            tokens.append(token)

    expanded: list[str] = []
    for token in tokens:
        if len(token) < 4:
            base = token[:2]
            suitedness = token[-1]
            if suitedness == "n":
                expanded.extend((base + "o", base + "s"))
            elif suitedness == "p":
                expanded.append(base)
            else:
                expanded.append(token)
        else:
            expanded.append(token)
    return expanded


def normalize_token(token: str) -> str:
    if token[0] == "#":
        return token

    if len(token) == 4:
        rank_indexes = [RANKS.index(rank.upper()) for rank in (token[0], token[2])]
        suit_indexes = [SUITS.index(suit.lower()) for suit in (token[1], token[3])]
        if rank_indexes[0] == rank_indexes[1] and suit_indexes[0] == suit_indexes[1]:
            raise RangeStringError("Invalid token: {}".format(token))
        if rank_indexes[0] < rank_indexes[1] or (
            rank_indexes[0] == rank_indexes[1] and suit_indexes[0] < suit_indexes[1]
        ):
            return token[2:] + token[:2]
        return token

    rank_indexes = sorted((RANKS.index(rank.upper()) for rank in token[:2]), reverse=True)
    return "".join(RANKS[index] for index in rank_indexes) + token_suitedness(token)


def token_suitedness(handtype: str) -> str:
    if len(handtype) == 3:
        if handtype[0].upper() == handtype[1].upper():
            raise RangeStringError("Pairs cannot have suitedness")
        return handtype[-1].lower()
    if handtype[0].upper() == handtype[1].upper():
        return "p"
    return "n"


def token_to_hands(handtype: str) -> list[tuple[str, str]]:
    """Expand one hand token into concrete card strings."""

    if len(handtype) == 4:
        return [(handtype[:2], handtype[2:])]

    suitedness = token_suitedness(handtype)
    hands: list[tuple[str, str]] = []
    for first_suit in SUITS:
        if suitedness == "s":
            second_suits = (first_suit,)
        elif suitedness == "o":
            second_suits = tuple(suit for suit in SUITS if suit != first_suit)
        elif suitedness == "p":
            second_suits = SUITS[SUITS.index(first_suit) + 1 :]
        else:
            raise RangeStringError("Unknown suitedness: {}".format(suitedness))

        for second_suit in second_suits:
            hand = (handtype[0].upper() + first_suit, handtype[1].upper() + second_suit)
            if suitedness == "p":
                hand = tuple(reversed(hand))  # type: ignore[assignment]
            hands.append(hand)
    return hands


def combo_key(cards: tuple[PokerEvalCard, PokerEvalCard]) -> tuple[tuple[int, int], tuple[int, int]]:
    left, right = cards
    return tuple(sorted(((int(left.rank), int(left.suit)), (int(right.rank), int(right.suit)))))


def _card_from_string(card_string: str) -> PokerEvalCard:
    try:
        rank = RANK_TO_POKEREVAL[card_string[0].upper()]
        suit = SUIT_TO_POKEREVAL[card_string[1].lower()]
    except (KeyError, IndexError) as exc:
        raise RangeStringError("Invalid card string: {}".format(card_string)) from exc
    return PokerEvalCard(rank, suit)


def _flatten(groups: Iterable[list[str]]) -> list[str]:
    return [token for group in groups for token in group]


def _make_parser():
    ranks = "".join(RANKS)
    ranks += ranks.lower()
    suits = "".join(SUITS)
    suits += suits.upper()
    suitedness = pyparsing.Word("osOS", exact=1).set_name("suitedness")
    card = pyparsing.Word(ranks, suits, exact=2).set_name("card")
    hand = card * 2
    hand.set_parse_action(lambda _s, _loc, toks: "".join(toks))
    digits = pyparsing.Word(pyparsing.nums)
    natural_number = pyparsing.Word("123456789", pyparsing.nums)
    decimal = (
        natural_number
        ^ (pyparsing.Optional(pyparsing.Literal("0")) + pyparsing.Literal(".") + digits)
        ^ (natural_number + pyparsing.Literal(".") + digits)
        ^ (natural_number + pyparsing.Literal("."))
    )
    decimal.set_parse_action(lambda _s, _loc, toks: "".join(toks))
    weight = pyparsing.Group(decimal + pyparsing.Optional(pyparsing.Literal("%")))
    handtype = (
        pyparsing.Word(ranks, exact=2)
        + pyparsing.Optional(suitedness)
        + ~pyparsing.FollowedBy(pyparsing.Literal("%") ^ pyparsing.Literal("("))
    )
    handtype.set_parse_action(lambda _s, _loc, toks: "".join(toks))
    tag = pyparsing.Literal("#") + pyparsing.Word(pyparsing.alphanums + "_") + pyparsing.Literal("#")
    handtype_group = pyparsing.Group(
        handtype
        ^ (handtype + pyparsing.Literal("-") + handtype)
        ^ (handtype + pyparsing.Literal("+"))
        ^ hand
        ^ tag
    )
    hand_group_list = pyparsing.Group(pyparsing.DelimitedList(handtype_group))
    weighted_hand_group_list = pyparsing.Group(
        (
            weight
            + pyparsing.Literal("(").suppress()
            + hand_group_list
            + pyparsing.Literal(")").suppress()
        )
        ^ hand_group_list
    )
    return pyparsing.Optional(pyparsing.DelimitedList(weighted_hand_group_list)) + pyparsing.StringEnd()


_PARSER = _make_parser()


__all__ = [
    "ParsedCombo",
    "RangeStringError",
    "cached_string_to_combos",
    "combo_key",
    "expand_handtype_group",
    "normalize_token",
    "string_to_combos",
    "string_to_tokens",
    "token_to_hands",
    "token_suitedness",
    "validate_string",
    "weight_to_float",
]
