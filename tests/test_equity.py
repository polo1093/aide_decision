"""Tests for weighted opponent-range equity simulation."""
from __future__ import annotations

from objet.entities.card import Card, CardsState
from objet.entities.player import Player, Players
from objet.services.equity import (
    OpponentProfile,
    opponent_profiles_from_players,
    profiles_for_opponent_count,
    starting_hand_strength,
    weighted_monte_carlo_equity,
)
from objet.services.game import Game


def _cards(*values: tuple[str, str]):
    out = []
    for value, suit in values:
        card = Card()
        card.apply_observation(value, suit)
        out.append(card.poker_card)
    return out


def test_weighted_equity_is_deterministic_for_same_profiles() -> None:
    hero = _cards(("A", "hearts"), ("K", "diamonds"))
    profile = OpponentProfile(name="villain", looseness=0.55, aggression=0.35)

    first = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[profile],
        simulations=500,
    )
    second = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[profile],
        simulations=500,
    )

    assert first == second
    assert 0 <= first <= 1


def test_tight_aggressive_range_reduces_weak_hero_equity() -> None:
    hero = _cards(("7", "hearts"), ("2", "diamonds"))
    loose = OpponentProfile(name="loose", looseness=1.0, aggression=0.0, action="play")
    tight = OpponentProfile(name="tight", looseness=0.05, aggression=1.0, action="raise")

    equity_vs_loose = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[loose],
        simulations=1200,
    )
    equity_vs_tight = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[tight],
        simulations=1200,
    )

    assert equity_vs_tight < equity_vs_loose


def test_explicit_pokerstove_range_changes_opponent_sampling() -> None:
    hero = _cards(("A", "hearts"), ("K", "diamonds"))
    weak_range = OpponentProfile(name="weak", range_string="72o", action="play")
    strong_range = OpponentProfile(name="strong", range_string="QQ+", action="play")

    equity_vs_weak = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[weak_range],
        simulations=1000,
    )
    equity_vs_strong = weighted_monte_carlo_equity(
        hero_cards=hero,
        board_cards=[],
        opponent_profiles=[strong_range],
        simulations=1000,
    )

    assert equity_vs_weak > equity_vs_strong


def test_starting_hand_strength_uses_pokermaster_preflop_ranking() -> None:
    aces = starting_hand_strength(_cards(("A", "hearts"), ("A", "diamonds")))
    seven_deuce = starting_hand_strength(_cards(("7", "hearts"), ("2", "diamonds")))
    ace_king_suited = starting_hand_strength(_cards(("A", "hearts"), ("K", "hearts")))
    ace_king_offsuit = starting_hand_strength(_cards(("A", "hearts"), ("K", "diamonds")))

    assert aces is not None
    assert seven_deuce is not None
    assert ace_king_suited is not None
    assert ace_king_offsuit is not None
    assert aces > ace_king_suited > ace_king_offsuit > seven_deuce


def test_profiles_reflect_observed_paid_player_state() -> None:
    passive = Player(name="passive", etat="play")
    paid = Player(name="paid", etat="paid", fond_start_Party=100)
    paid.fond.amount = 80

    profiles = opponent_profiles_from_players([passive, paid])

    assert len(profiles) == 2
    assert profiles[1].looseness < profiles[0].looseness
    assert profiles[1].aggression > profiles[0].aggression
    assert profiles[1].action == "paid"


def test_profiles_for_opponent_count_pads_defaults() -> None:
    profiles = profiles_for_opponent_count([OpponentProfile(name="J1")], 3)

    assert [profile.name for profile in profiles] == ["J1", "opponent_2", "opponent_3"]


def test_game_update_uses_weighted_opponent_profiles() -> None:
    game = Game()
    game.etat.monte_carlo_simulations = 100

    scanned = CardsState()
    scanned.me[0].apply_observation("A", "hearts")
    scanned.me[1].apply_observation("K", "diamonds")

    players = Players(player=[Player(etat="paid"), Player(etat="play")])
    game.etat.update(cards_state=scanned, players=players, pot=0.10)

    assert game.etat.chance_win is not None
    assert [profile.action for profile in game.etat.opponent_profiles] == ["paid", "play"]
