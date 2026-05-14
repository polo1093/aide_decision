"""Tests for long-term player tendency storage."""
from __future__ import annotations

from pathlib import Path

from objet.entities.card import CardsState
from objet.entities.player import Player, Players
from objet.services.equity import opponent_profiles_from_players
from objet.services.game import Game
from objet.services.player_history import PlayerHistoryStore


def _paid_player(name: str, *, start: float = 100.0, current: float = 90.0) -> Player:
    player = Player(name=name, etat="paid", fond_start_Party=start)
    player.fond.amount = current
    return player


def test_player_history_records_once_per_hand_and_clears(tmp_path: Path) -> None:
    store = PlayerHistoryStore(root_dir=tmp_path, game_name="PMU")
    player = _paid_player("Alice", current=80.0)

    store.record_players([player], hand_id=1)
    store.record_players([player], hand_id=1)

    stats = store.stats_for("Alice")
    assert stats is not None
    assert stats["hands"] == 1
    assert stats["calls"] == 1
    assert stats["invested_total"] == 20.0
    assert store.path.exists()

    cleared_path = store.clear()

    assert cleared_path == store.path
    assert not store.path.exists()
    assert store.player_count() == 0


def test_player_history_blends_observed_profile_with_memory(tmp_path: Path) -> None:
    store = PlayerHistoryStore(root_dir=tmp_path, game_name="PMU")
    for hand_id in range(1, 31):
        store.record_players([_paid_player("Caller")], hand_id=hand_id)

    current_player = _paid_player("Caller")
    base = opponent_profiles_from_players([current_player])[0]
    adjusted = store.opponent_profiles_from_players([current_player])[0]

    assert adjusted.confidence > 0
    assert adjusted.looseness > base.looseness
    assert adjusted.action == base.action


def test_game_update_records_history_and_uses_adjusted_profiles(tmp_path: Path) -> None:
    store = PlayerHistoryStore(root_dir=tmp_path, game_name="PMU")
    game = Game(player_history=store)
    game.etat.monte_carlo_simulations = 50

    game.table.cards = CardsState()
    game.table.cards.me[0].apply_observation("A", "hearts")
    game.table.cards.me[1].apply_observation("K", "diamonds")
    game.table.players = Players(player=[_paid_player("Caller")])
    game.table.pot.amount = 0.10

    assert game.update_from_scan() is False

    assert store.player_count() == 1
    assert game.etat.opponent_profiles
    assert game.etat.opponent_profiles[0].confidence > 0
