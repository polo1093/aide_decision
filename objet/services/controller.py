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
DEFAULT_HERO_POSITION = "BTN"


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
    target_button: Optional[dict[str, object]] = None
    opponent_profiles: list[str] = field(default_factory=list)
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
    hero_position: str = DEFAULT_HERO_POSITION
    hero_position_reason: str = ""
    hero_position_confidence: object = None

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
            f"Position hero: {self.hero_position} ({self.hero_position_reason})\n"
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
            f" Bouton cible: {self.target_button}\n"
            f" Profils adverses: {self.opponent_profiles}\n"
            f"Decision -> {decision_line}\n"
        )


class Controller:
    def __init__(
        self,
        *,
        game_name: str = "PMU",
        coord_path: Optional[Path | str] = None,
        telemetry_dir: Optional[Path | str] = None,
        telemetry_enabled: bool = True,
        telemetry_recorder=None,
        player_history_dir: Optional[Path | str] = None,
        player_history_enabled: bool = True,
        player_history_store=None,
        decision_mode: str = "legacy",
        hero_position: str = DEFAULT_HERO_POSITION,
        auto_hero_position: bool = True,
    ):
        self.count = 0
        self.running = False
        self.cpt = 0
        self.game_stat = {}
        self.game_name = game_name
        self.coord_path = Path(coord_path) if coord_path is not None else Path("config") / game_name / "coordinates.json"
        from objet.services.decision import Decision
        from objet.services.game import Game
        from objet.services.player_history import DEFAULT_PLAYER_HISTORY_DIR, PlayerHistoryStore
        from objet.services.telemetry import DEFAULT_TELEMETRY_DIR, TelemetryRecorder
        from objet.services.range_analyzer import normalize_position

        self.hero_position = normalize_position(hero_position) or DEFAULT_HERO_POSITION
        self.auto_hero_position = bool(auto_hero_position)
        self.hero_position_reason = "manual_fallback"
        self.hero_position_confidence = 0.0
        self.player_history = (
            player_history_store
            if player_history_store is not None
            else PlayerHistoryStore(
                root_dir=player_history_dir if player_history_dir is not None else DEFAULT_PLAYER_HISTORY_DIR,
                game_name=game_name,
                enabled=player_history_enabled,
            )
        )
        self.game = Game(coord_path=self.coord_path, player_history=self.player_history)
        self.set_hero_position(self.hero_position)
        self.decision = Decision(mode=decision_mode)
        self.telemetry = (
            telemetry_recorder
            if telemetry_recorder is not None
            else TelemetryRecorder(
                root_dir=telemetry_dir if telemetry_dir is not None else DEFAULT_TELEMETRY_DIR,
                game_name=game_name,
                enabled=telemetry_enabled,
            )
        )
        self.last_view_state: Optional[ControllerViewState] = None

    def main(self) -> str:
        return self.run_cycle().to_text()

    def clear_player_history(self) -> Path:
        return self.player_history.clear()

    def set_hero_position(self, position: str) -> None:
        from objet.services.range_analyzer import normalize_position

        normalized = normalize_position(position) or DEFAULT_HERO_POSITION
        self.hero_position = normalized
        self.hero_position_reason = "manual_fallback"
        self.hero_position_confidence = 0.0
        setattr(self.game, "range_position", normalized)
        if getattr(self.game, "etat", None) is not None:
            setattr(self.game.etat, "range_position", normalized)

    def detect_hero_position(self) -> None:
        if not self.auto_hero_position:
            self.set_hero_position(self.hero_position)
            return
        from objet.services.position_detector import detect_hero_position

        detection = detect_hero_position(self.game, fallback=self.hero_position)
        self.hero_position = detection.position
        self.hero_position_reason = detection.reason
        self.hero_position_confidence = detection.confidence
        setattr(self.game, "range_position", detection.position)
        if getattr(self.game, "etat", None) is not None:
            setattr(self.game.etat, "range_position", detection.position)

    def run_cycle(self) -> ControllerViewState:
        self.count += 1
        LOGGER.info("debut cycle_controller count=%s", self.count)
        if self.game.scan_to_data_table():
            new_party = self.game.update_from_scan()
            self.detect_hero_position()
            result = self.game_stat_to_view_state(new_party)
            self.last_view_state = result
            self.telemetry.record_cycle(game=self.game, view_state=result)
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
            f"{getattr(player, 'name', None) or f'J{i + 1}'} {'active' if player.is_activate() else 'inactive'} : {player.fond}"
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
        target_button = button_target_for_action(self.game.table.buttons, decision_result.action)
        opponent_profiles = [
            (
                f"{profile.name} {profile.action} "
                f"loose={profile.looseness:.2f} aggro={profile.aggression:.2f}"
                + (f" mem={profile.confidence:.2f}" if profile.confidence else "")
            )
            for profile in getattr(self.game.etat, "opponent_profiles", [])
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
            target_button=target_button,
            opponent_profiles=opponent_profiles,
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
            hero_position=self.hero_position,
            hero_position_reason=self.hero_position_reason,
            hero_position_confidence=round_sig(self.hero_position_confidence),
        )


ACTION_BUTTON_STATES = {
    "FOLD": ("fold",),
    "CALL": ("paie",),
    "CHECK": ("check",),
    "RAISE": ("relance", "mise", "all-in"),
}


def button_target_for_action(buttons, action: str) -> Optional[dict[str, object]]:
    expected_states = ACTION_BUTTON_STATES.get(action)
    if not expected_states:
        return None

    expected = {state.lower() for state in expected_states}
    for index, button in enumerate(buttons):
        if not getattr(button, "enabled", False):
            continue
        state = str(getattr(button, "etat", "")).lower()
        if state not in expected:
            continue
        bbox = getattr(button, "coordonate", None)
        if not bbox:
            continue
        return {
            "index": index,
            "label": f"B{index}",
            "state": state,
            "text": getattr(button, "texte", ""),
            "value": getattr(button, "value", 0.0),
            "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
        }
    return None


__all__ = ["Controller", "ControllerViewState", "button_target_for_action"]


if __name__ == "__main__":
    controller = Controller()
    print(controller.main())
