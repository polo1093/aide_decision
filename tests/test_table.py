"""Tests for table scanning state updates."""
from __future__ import annotations

from objet.services.table import Table


class EmptyScan:
    def test_scan(self) -> bool:
        return True

    def scan_carte(self, **_) -> tuple[None, None, None, None]:
        return None, None, None, None

    def scan_player(self, **_) -> tuple[str, None]:
        return "play", None

    def scan_bouton(self, **_) -> None:
        return None

    def scan_money(self, _) -> None:
        return None


def test_empty_board_scan_clears_previous_card() -> None:
    table = Table()
    table.scan = EmptyScan()
    table.cards.board[0].apply_observation("A", "hearts")

    assert table.cards.board[0].formatted == "A♥"

    assert table.launch_scan() is True

    assert table.cards.board[0].formatted is None
    assert table.cards.board[0].poker_card is None
