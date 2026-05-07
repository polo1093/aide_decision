"""Orchestrateur haut niveau entre scan, etat de jeu et decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.logging_config import get_logger


LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class ControllerViewState:
    """Etat structure pour alimenter l'interface sans parser le texte."""

    game_name: str
    scan_count: int
    scan_ok: bool
    scan_failures: int
    hand_id: Optional[int] = None
    street: str = "IDLE"
    status: str = ""
    new_party_state: Optional[bool] = False
    hero_scan: list[Optional[str]] = field(default_factory=list)
    board_scan: list[Optional[str]] = field(default_factory=list)
    hero_state: list[Optional[str]] = field(default_factory=list)
    board_state: list[Optional[str]] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    player_start: Optional[int] = None
    player_active: Optional[int] = None
    buttons: list[str] = field(default_factory=list)
    pot: object = None
    to_call: object = None
    equity_table: object = None
    equity_1v1: object = None
    equity_required: object = None
    ev: object = None
    call_max: object = None
    decision_action: str = "WAIT"
    decision_reason: str = ""
    raise_amount: object = None

    def notice(self) -> str:
        if self.new_party_state is True:
            return "Nouvelle partie detectee (pot en baisse)."
        if self.new_party_state is None:
            return "Pot non detecte, impossible de statuer sur la nouvelle partie."
        return ""

    def to_text(self) -> str:
        if not self.scan_ok:
            return f"don t find     Scan n°{self.scan_failures}"

        decision_line = f"Action: {self.decision_action} (raison: {self.decision_reason})"
        if self.raise_amount is not None:
            decision_line += f" | Raise: {self.raise_amount}"

        metrics = " | ".join(
            [
                f"Pot: {self.pot}",
                f"To call: {self.to_call}",
                f"Equity table: {self.equity_table}",
                f"Equity 1v1: {self.equity_1v1}",
                f"Equity min call: {self.equity_required}",
                f"Ev: {self.ev}",
                f"Call_max: {self.call_max}",
            ]
        )

        notice = self.notice()
        notice_line = f"{notice}\n" if notice else ""
        return (
            f"{notice_line}"
            f"Partie: {self.hand_id}\n"
            f"Jeu: {self.game_name}\n"
            f"Street: {self.street}\n"
            f"Mes cartes: {self.hero_scan}\n"
            f"Cartes sur le board: {self.board_scan}\n"
            f"{self.players}\n"
            f"{'=' * 30}ETAT{'=' * 30}\n"
            f"Mes cartes: {self.hero_state}\n"
            f"Cartes sur le board: {self.board_state}\n"
            f"Player start {self.player_start}    Player active {self.player_active}\n"
            f"{'=' * 30}Metriques{'=' * 30}\n"
            f" {metrics}\n"
            f" {'  |  '.join(self.buttons)}\n"
            f"Decision -> {decision_line}\n"
        )


class Controller:
    def __init__(self, *, game_name: str = "PMU", coord_path: Optional[Path | str] = None):
        self.count = 0
        self.running = False
        self.cpt = 0
        self.game_stat = {}
        self.game_name = game_name
        self.coord_path = Path(coord_path) if coord_path is not None else Path("config") / game_name / "coordinates.json"
        from objet.services.decision import Decision
        from objet.services.game import Game

        self.game = Game(coord_path=self.coord_path)
        self.decision = Decision()
        self.last_view_state: Optional[ControllerViewState] = None

    def main(self) -> str:
        return self.run_cycle().to_text()

    def run_cycle(self) -> ControllerViewState:
        self.count += 1
        LOGGER.info("debut cycle_controller count=%s", self.count)
        if self.game.scan_to_data_table():
            new_party = self.game.update_from_scan()
            result = self.game_stat_to_view_state(new_party)
            self.last_view_state = result
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
        result = ControllerViewState(
            game_name=self.game_name,
            scan_count=self.count,
            scan_ok=False,
            scan_failures=self.cpt,
            hand_id=getattr(self.game, "hand_id", None),
            street=getattr(self.game, "street", "IDLE"),
            status="table_introuvable",
        )
        self.last_view_state = result
        return result

    def game_stat_to_view_state(self, new_party_state: Optional[bool] = None) -> ControllerViewState:
        def round_sig(x, sig=4):
            if isinstance(x, (int, float)):
                return float(f"{x:.{sig}g}")
            return x

        decision_result = self.decision.decide(self.game)
        player_scan = [
            f"J{i + 1} {'active' if player.is_activate() else 'inactive'} : {player.fond}"
            for i, player in enumerate(self.game.table.players)
        ]
        buttons = [
            f"B{i} {button.etat} :{button.value}"
            if button.value != 0
            else f"B{i} {button.etat}"
            if button.enabled
            else ""
            for i, button in enumerate(self.game.table.buttons)
        ]

        return ControllerViewState(
            game_name=self.game_name,
            scan_count=self.count,
            scan_ok=True,
            scan_failures=self.cpt,
            hand_id=self.game.hand_id,
            street=self.game.street,
            status="ok",
            new_party_state=new_party_state,
            hero_scan=[card.formatted for card in self.game.table.cards.me_cards()],
            board_scan=[card.formatted for card in self.game.table.cards.board_cards()],
            hero_state=[card.formatted for card in self.game.etat.cards.me_cards()],
            board_state=[card.formatted for card in self.game.etat.cards.board_cards()],
            players=player_scan,
            player_start=self.game.etat.players.nbr_player_start,
            player_active=self.game.etat.players.nbr_player_active,
            buttons=buttons,
            pot=round_sig(self.game.etat.pot),
            to_call=round_sig(self.game.etat.to_call),
            equity_table=round_sig(self.game.etat.chance_win),
            equity_1v1=round_sig(self.game.etat.chance_win_0),
            equity_required=round_sig(self.game.etat.equity_required),
            ev=round_sig(self.game.etat.ev),
            call_max=round_sig(self.game.etat.Call_max),
            decision_action=decision_result.action,
            decision_reason=decision_result.reason,
            raise_amount=round_sig(decision_result.raise_amount),
        )


__all__ = ["Controller", "ControllerViewState"]


if __name__ == "__main__":
    controller = Controller()
    print(controller.main())
