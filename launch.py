"""Interface Tkinter pour suivre le scan live et la decision."""

from __future__ import annotations

import argparse
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

from objet.services.controller import Controller, ControllerViewState
from objet.utils.debug_capture import capture_blocking_error_screen
from objet.utils.logging_config import (
    configure_logging,
    get_logger,
    log_path_value,
    session_log,
)


logger = get_logger(__name__)


class App(tk.Tk):
    def __init__(self, controller: Controller, scan_interval_ms: int = 1000, game_name: str = "PMU"):
        super().__init__()

        self.title("Aide decision - table live")
        self.geometry("1080x760")
        self.minsize(960, 640)

        self.controller = controller
        self.game_name = game_name
        self.game_profiles = available_game_names()

        self.scanning = False
        self.scan_interval_ms = scan_interval_ms
        self._last_tick_t: Optional[float] = None

        self.last_call_ms: Optional[float] = None
        self.fps: Optional[float] = None
        self._blink_after_id: Optional[str] = None
        self._blink_on = False
        self._base_decision_color = "#6c757d"

        self.metric_vars: dict[str, tk.StringVar] = {}
        self.metric_value_labels: dict[str, tk.Label] = {}
        self.summary_value_labels: dict[str, tk.Label] = {}
        self.profile_labels: list[tk.Label] = []

        self._build()
        self._layout()
        self._bind_keys()
        self._refresh_profile_status()
        self._apply_empty_state()

    def _build(self) -> None:
        self.style = ttk.Style(self)
        self.style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))
        self.configure(bg="#f4f6f8")

        self.frm_top = ttk.Frame(self)
        self.btn_start = ttk.Button(self.frm_top, text="Start", command=self.start_scan)
        self.btn_stop = ttk.Button(self.frm_top, text="Stop", command=self.stop_scan)
        self.btn_snap = ttk.Button(self.frm_top, text="Snapshot", command=self.snapshot_once)
        self.lbl_game = ttk.Label(self.frm_top, text="Jeu")
        self.var_game = tk.StringVar(value=self.game_name)
        self.cmb_game = ttk.Combobox(
            self.frm_top,
            width=18,
            textvariable=self.var_game,
            values=self.game_profiles,
            state="readonly",
        )
        self.lbl_interval = ttk.Label(self.frm_top, text="Interval ms")
        self.var_interval = tk.StringVar(value=str(self.scan_interval_ms))
        self.ent_interval = ttk.Entry(self.frm_top, width=7, textvariable=self.var_interval)
        self.var_perf = tk.StringVar(value="scan: --- ms | fps: ---")
        self.lbl_perf = ttk.Label(self.frm_top, textvariable=self.var_perf)

        self.main = ttk.Frame(self)

        self.frm_summary = ttk.LabelFrame(self.main, text="Etat")
        self.var_scan = tk.StringVar(value="---")
        self.var_hand = tk.StringVar(value="---")
        self.var_street = tk.StringVar(value="---")
        self.var_action_available = tk.StringVar(value="---")
        self.var_notice = tk.StringVar(value="")

        self.frm_decision = ttk.LabelFrame(self.main, text="Decision")
        self.var_decision = tk.StringVar(value="WAIT")
        self.var_reason = tk.StringVar(value="")
        self.lbl_decision = tk.Label(
            self.frm_decision,
            textvariable=self.var_decision,
            font=("Segoe UI", 30, "bold"),
            bg="#6c757d",
            fg="white",
            width=10,
            pady=10,
        )
        self.lbl_reason = tk.Label(
            self.frm_decision,
            textvariable=self.var_reason,
            wraplength=360,
            justify="left",
            bg="#f8fafc",
            fg="#1f2937",
            padx=10,
            pady=8,
        )

        self.frm_cards = ttk.LabelFrame(self.main, text="Cartes")
        self.hero_vars = [tk.StringVar(value="--") for _ in range(2)]
        self.board_vars = [tk.StringVar(value="--") for _ in range(5)]
        self.hero_labels = [
            tk.Label(
                self.frm_cards,
                textvariable=var,
                font=("Consolas", 21, "bold"),
                width=5,
                bg="#ffffff",
                fg="#111827",
                relief="solid",
                bd=1,
                pady=8,
            )
            for var in self.hero_vars
        ]
        self.board_labels = [
            tk.Label(
                self.frm_cards,
                textvariable=var,
                font=("Consolas", 16, "bold"),
                width=5,
                bg="#ffffff",
                fg="#111827",
                relief="solid",
                bd=1,
                pady=6,
            )
            for var in self.board_vars
        ]

        self.frm_metrics = ttk.LabelFrame(self.main, text="Metriques")
        for key in ["Pot", "To call", "Equity", "Equity 1v1", "Equity min", "EV", "Call max"]:
            self.metric_vars[key] = tk.StringVar(value="---")

        self.frm_side = ttk.Frame(self.main)
        self.frm_profile = ttk.LabelFrame(self.frm_side, text="Profil")
        self.frm_players = ttk.LabelFrame(self.frm_side, text="Joueurs")
        self.var_players = tk.StringVar(value="")
        self.lbl_players = tk.Label(
            self.frm_players,
            textvariable=self.var_players,
            justify="left",
            anchor="nw",
            bg="#ffffff",
            fg="#111827",
            padx=10,
            pady=8,
        )
        self.frm_buttons = ttk.LabelFrame(self.frm_side, text="Boutons")
        self.var_buttons = tk.StringVar(value="")
        self.lbl_buttons = tk.Label(
            self.frm_buttons,
            textvariable=self.var_buttons,
            justify="left",
            anchor="nw",
            wraplength=280,
            bg="#ffffff",
            fg="#111827",
            padx=10,
            pady=8,
        )

        self.frm_debug = ttk.LabelFrame(self.main, text="Debug")
        self.txt = tk.Text(
            self.frm_debug,
            height=8,
            wrap="none",
            font=("Consolas", 10),
            state="disabled",
            bg="#111827",
            fg="#e5e7eb",
            insertbackground="#e5e7eb",
            selectbackground="#374151",
        )
        self.scroll = ttk.Scrollbar(self.frm_debug, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=self.scroll.set)

    def _layout(self) -> None:
        self.frm_top.pack(side="top", fill="x", padx=10, pady=8)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop.pack(side="left", padx=(0, 6))
        self.btn_snap.pack(side="left", padx=(0, 16))
        self.lbl_game.pack(side="left")
        self.cmb_game.pack(side="left", padx=(6, 14))
        self.lbl_interval.pack(side="left")
        self.ent_interval.pack(side="left", padx=(6, 16))
        self.lbl_perf.pack(side="left", padx=(10, 0))

        self.main.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 10))
        self.main.grid_columnconfigure(0, weight=3)
        self.main.grid_columnconfigure(1, weight=2)
        self.main.grid_rowconfigure(2, weight=0)
        self.main.grid_rowconfigure(3, weight=1)

        self.frm_summary.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.frm_decision.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=(0, 8))
        self.frm_cards.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.frm_metrics.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        self.frm_side.grid(row=1, column=1, rowspan=2, sticky="nsew", pady=(0, 8))
        self.frm_debug.grid(row=3, column=0, columnspan=2, sticky="nsew")

        self._layout_summary()
        self._layout_decision()
        self._layout_cards()
        self._layout_metrics()
        self._layout_side()
        self._layout_debug()

    def _layout_summary(self) -> None:
        items = [
            ("Scan", self.var_scan),
            ("Partie", self.var_hand),
            ("Street", self.var_street),
            ("Action", self.var_action_available),
            ("Info", self.var_notice),
        ]
        for col, (label, var) in enumerate(items):
            ttk.Label(self.frm_summary, text=label, style="Title.TLabel").grid(row=0, column=col, sticky="w", padx=10, pady=(8, 2))
            value_label = tk.Label(
                self.frm_summary,
                textvariable=var,
                bg="#ffffff",
                fg="#111827",
                padx=8,
                pady=4,
                anchor="w",
            )
            value_label.grid(row=1, column=col, sticky="ew", padx=10, pady=(0, 8))
            self.summary_value_labels[label] = value_label
            self.frm_summary.grid_columnconfigure(col, weight=1)

    def _layout_decision(self) -> None:
        self.lbl_decision.pack(side="top", fill="x", padx=12, pady=(12, 8))
        self.lbl_reason.pack(side="top", fill="x", padx=12, pady=(0, 12))

    def _layout_cards(self) -> None:
        ttk.Label(self.frm_cards, text="Hero", style="Title.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        for i, label in enumerate(self.hero_labels):
            label.grid(row=0, column=i + 1, sticky="ew", padx=4, pady=10)

        ttk.Label(self.frm_cards, text="Board", style="Title.TLabel").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        for i, label in enumerate(self.board_labels):
            label.grid(row=1, column=i + 1, sticky="ew", padx=4, pady=10)

    def _layout_metrics(self) -> None:
        for index, (label, var) in enumerate(self.metric_vars.items()):
            row = index // 2
            col = (index % 2) * 2
            ttk.Label(self.frm_metrics, text=label).grid(row=row, column=col, sticky="w", padx=12, pady=8)
            value_label = tk.Label(
                self.frm_metrics,
                textvariable=var,
                font=("Consolas", 13, "bold"),
                bg="#ffffff",
                fg="#111827",
                padx=8,
                pady=4,
                anchor="w",
            )
            value_label.grid(
                row=row, column=col + 1, sticky="w", padx=(0, 20), pady=8
            )
            self.metric_value_labels[label] = value_label
        self.frm_metrics.grid_columnconfigure(1, weight=1)
        self.frm_metrics.grid_columnconfigure(3, weight=1)

    def _layout_side(self) -> None:
        self.frm_side.grid_rowconfigure(1, weight=1)
        self.frm_profile.pack(side="top", fill="x", pady=(0, 8))
        self.frm_players.pack(side="top", fill="both", expand=True, pady=(0, 8))
        self.frm_buttons.pack(side="top", fill="x")
        self.lbl_players.pack(side="top", anchor="w", padx=12, pady=10)
        self.lbl_buttons.pack(side="top", anchor="w", fill="x", padx=12, pady=10)

    def _layout_debug(self) -> None:
        self.txt.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

    def _bind_keys(self) -> None:
        self.bind("<Escape>", lambda _e: self.stop_scan())
        self.bind("<F5>", lambda _e: self.start_scan())
        self.bind("<F6>", lambda _e: self.snapshot_once())
        self.ent_interval.bind("<Return>", lambda _e: self._update_interval())
        self.cmb_game.bind("<<ComboboxSelected>>", lambda _e: self._switch_game())

    def _apply_empty_state(self) -> None:
        self.var_scan.set("pret")
        self.var_hand.set("---")
        self.var_street.set("---")
        self.var_action_available.set("---")
        self.var_notice.set("")
        self.var_players.set("")
        self.var_buttons.set("")
        self._set_text("")

    def _set_text(self, text: str) -> None:
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")

    def _update_interval(self) -> None:
        try:
            value = int(self.var_interval.get())
            self.scan_interval_ms = max(25, min(2000, value))
        except Exception:
            self.scan_interval_ms = 1000
            self.var_interval.set(str(self.scan_interval_ms))

    def _switch_game(self) -> None:
        selected = self.var_game.get().strip()
        if not selected or selected == self.game_name:
            return

        self.stop_scan()
        logger.info("changement_jeu old=%s new=%s", self.game_name, selected)
        try:
            self.controller = Controller(game_name=selected)
        except Exception as exc:
            self.var_game.set(self.game_name)
            self._handle_controller_exception(context=f"Changement jeu {selected}", error=exc)
            raise

        self.game_name = selected
        self.last_call_ms = None
        self.fps = None
        self.var_perf.set("scan: --- ms | fps: ---")
        self._apply_empty_state()
        self._refresh_profile_status()

    def start_scan(self) -> None:
        self._update_interval()
        self.scanning = True
        self._last_tick_t = time.time()
        logger.info("debut scan_continu interval_ms=%s", self.scan_interval_ms)
        self.after(1, self._tick)

    def stop_scan(self) -> None:
        if self.scanning:
            logger.info("fin scan_continu last_ms=%s", _fmt_optional_float(self.last_call_ms))
        self.scanning = False
        self._stop_decision_blink()

    def snapshot_once(self) -> None:
        logger.info("debut snapshot")
        state, dt_ms = self._run_controller(context="Snapshot")
        self.last_call_ms = dt_ms
        self.fps = None
        self._apply_view_state(state)
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: ---")
        logger.info("fin snapshot status=ok duree_ms=%.1f", dt_ms)

    def _tick(self) -> None:
        if not self.scanning:
            return

        state, dt_ms = self._run_controller(context="Scan continu")
        self.last_call_ms = dt_ms

        now = time.time()
        if self._last_tick_t is not None:
            dt_s = max(now - self._last_tick_t, 1e-6)
            self.fps = 1.0 / dt_s
        else:
            self.fps = None
        self._last_tick_t = now

        self._apply_view_state(state)
        fps_txt = f"{self.fps:.1f}" if self.fps else "---"
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: {fps_txt}")

        if self.scanning:
            next_delay = max(1, self.scan_interval_ms - int(dt_ms))
            self.after(next_delay, self._tick)

    def _run_controller(self, *, context: str) -> tuple[ControllerViewState, float]:
        t0 = time.perf_counter()
        try:
            state = self.controller.run_cycle()
        except Exception as exc:
            self._handle_controller_exception(context=context, error=exc)
            raise
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return state, dt_ms

    def _apply_view_state(self, state: ControllerViewState) -> None:
        self.var_scan.set("OK" if state.scan_ok else f"table absente ({state.scan_failures})")
        self.var_hand.set(_display_value(state.hand_id))
        self.var_street.set(state.street)
        self.var_notice.set(state.notice())
        active_buttons = [button for button in state.buttons if button]
        action_available = bool(active_buttons)
        self.var_action_available.set("oui" if action_available else "non")

        self.var_decision.set(state.decision_action)
        self.var_reason.set(_decision_explanation(state.decision_action, state.decision_reason))
        self._set_decision_color(state.decision_action, blink=action_available)

        for var, value in zip(self.hero_vars, _pad_list(state.hero_state or state.hero_scan, 2)):
            var.set(_display_card(value))
        for label, value in zip(self.hero_labels, _pad_list(state.hero_state or state.hero_scan, 2)):
            _style_card_label(label, value)
        for var, value in zip(self.board_vars, _pad_list(state.board_state or state.board_scan, 5)):
            var.set(_display_card(value))
        for label, value in zip(self.board_labels, _pad_list(state.board_state or state.board_scan, 5)):
            _style_card_label(label, value)

        self.metric_vars["Pot"].set(_display_value(state.pot))
        self.metric_vars["To call"].set(_display_value(state.to_call))
        self.metric_vars["Equity"].set(_display_percent(state.equity_table))
        self.metric_vars["Equity 1v1"].set(_display_percent(state.equity_1v1))
        self.metric_vars["Equity min"].set(_display_percent(state.equity_required))
        self.metric_vars["EV"].set(_display_value(state.ev))
        self.metric_vars["Call max"].set(_display_value(state.call_max))
        self._style_metrics(state)
        self._style_summary(action_available)

        players_header = f"Actifs: {_display_value(state.player_active)} / {_display_value(state.player_start)}"
        self.var_players.set(players_header + "\n" + "\n".join(state.players))
        self.var_buttons.set("\n".join(active_buttons) if active_buttons else "aucun bouton actif")
        self._set_text(state.to_text())

    def _style_summary(self, action_available: bool) -> None:
        scan_label = self.summary_value_labels.get("Scan")
        if scan_label is not None:
            if self.var_scan.get() == "OK":
                scan_label.configure(bg="#dcfce7", fg="#166534")
            elif self.var_scan.get().startswith("table"):
                scan_label.configure(bg="#fee2e2", fg="#991b1b")
            else:
                scan_label.configure(bg="#f3f4f6", fg="#374151")

        action_label = self.summary_value_labels.get("Action")
        if action_label is not None:
            action_label.configure(
                bg="#dcfce7" if action_available else "#f3f4f6",
                fg="#166534" if action_available else "#374151",
            )

    def _style_metrics(self, state: ControllerViewState) -> None:
        _style_metric_label(self.metric_value_labels.get("EV"), state.ev, positive_good=True)
        _style_metric_label(self.metric_value_labels.get("Call max"), state.call_max, positive_good=True)
        _style_equity_label(self.metric_value_labels.get("Equity"), state.equity_table)
        _style_equity_label(self.metric_value_labels.get("Equity 1v1"), state.equity_1v1)

    def _set_decision_color(self, action: str, *, blink: bool = False) -> None:
        colors = {
            "WAIT": "#6c757d",
            "FOLD": "#b02a37",
            "CALL": "#0d6efd",
            "CHECK": "#198754",
            "RAISE": "#b26a00",
        }
        self._base_decision_color = colors.get(action, "#6c757d")
        if blink:
            self._start_decision_blink()
        else:
            self._stop_decision_blink()
            self.lbl_decision.configure(bg=self._base_decision_color)

    def _start_decision_blink(self) -> None:
        if self._blink_after_id is not None:
            return
        self._blink_on = False
        self._blink_decision()

    def _blink_decision(self) -> None:
        self._blink_on = not self._blink_on
        color = _lighten_hex(self._base_decision_color, 0.18) if self._blink_on else self._base_decision_color
        self.lbl_decision.configure(bg=color)
        self._blink_after_id = self.after(450, self._blink_decision)

    def _stop_decision_blink(self) -> None:
        if self._blink_after_id is not None:
            self.after_cancel(self._blink_after_id)
            self._blink_after_id = None
        self._blink_on = False

    def _refresh_profile_status(self) -> None:
        for label in self.profile_labels:
            label.destroy()
        self.profile_labels = []

        for row, item in enumerate(profile_status(self.game_name)):
            text = f"{'[OK]' if item.ok else '[--]'} {item.label}: {item.detail}"
            label = tk.Label(
                self.frm_profile,
                text=text,
                anchor="w",
                justify="left",
                bg="#dcfce7" if item.ok else "#ffedd5",
                fg="#166534" if item.ok else "#9a3412",
                padx=8,
                pady=4,
            )
            label.grid(row=row, column=0, sticky="w", padx=12, pady=(8 if row == 0 else 2, 2))
            self.profile_labels.append(label)

    def _handle_controller_exception(self, context: str, error: Exception) -> None:
        screenshot_path = capture_blocking_error_screen(context=context)
        self.last_call_ms = None
        self.fps = None
        self.var_scan.set("erreur")
        self.var_notice.set(str(error))
        self._set_text(f"Erreur Controller: {error}")
        self.var_perf.set("scan: --- ms | fps: ---")
        logger.exception(
            "ARRET - erreur controller contexte=%s error=%s screenshot=%s",
            context,
            error,
            log_path_value(screenshot_path) if screenshot_path else None,
        )


class ProfileItem:
    def __init__(self, label: str, ok: bool, detail: str) -> None:
        self.label = label
        self.ok = ok
        self.detail = detail


def profile_status(game_name: str, config_root: Path | str = "config") -> list[ProfileItem]:
    game_dir = Path(config_root) / game_name
    action_files = ["check.png", "paie.png", "relance.png", "fold.png", "sit_out.png", "play.png"]
    cards_dir = game_dir / "Cards"
    cards_png = list(cards_dir.rglob("*.png")) if cards_dir.exists() else []
    return [
        _profile_item("Dossier", game_dir, "profil"),
        _profile_item("Coordinates", game_dir / "coordinates.json", "zones"),
        _profile_item("Anchor", game_dir / "anchor.png", "ancre"),
        ProfileItem("Cards", bool(cards_png), f"{len(cards_png)} templates" if cards_png else "templates manquants"),
        ProfileItem(
            "Actions",
            all((game_dir / name).exists() for name in action_files),
            f"{sum(1 for name in action_files if (game_dir / name).exists())}/{len(action_files)} fichiers",
        ),
    ]


def _profile_item(label: str, path: Path, detail: str) -> ProfileItem:
    return ProfileItem(label, path.exists(), detail if path.exists() else "manquant")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="UI autour de Controller.run_cycle()")
    parser.add_argument("--interval", type=int, default=1000, help="Intervalle entre deux scans en ms (25..2000)")
    parser.add_argument("--game", default="PMU", help="Nom du jeu/profil dans config/ (default: PMU)")
    parser.add_argument("--list-games", action="store_true", help="Liste les profils disponibles puis quitte.")
    parser.add_argument("--snapshot", action="store_true", help="Execute un seul scan dans le terminal.")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.list_games:
        for name in available_game_names():
            print(name)
        return

    configure_logging()
    with session_log("interface") as log_file:
        logger.info("debut interface interval_ms=%s log=%s", args.interval, log_path_value(log_file))
        controller = Controller(game_name=args.game)
        if args.snapshot:
            try:
                print(controller.main())
            except Exception as exc:
                screenshot_path = capture_blocking_error_screen(context="Snapshot CLI")
                logger.exception(
                    "ARRET - erreur controller contexte=%s error=%s screenshot=%s",
                    "Snapshot CLI",
                    exc,
                    log_path_value(screenshot_path) if screenshot_path else None,
                )
                raise
            logger.info("fin snapshot_cli status=ok log=%s", log_path_value(log_file))
            return

        app = App(controller=controller, scan_interval_ms=args.interval, game_name=args.game)
        app.mainloop()
        logger.info("fin interface status=closed log=%s", log_path_value(log_file))


def available_game_names(config_root: Path | str = "config") -> list[str]:
    root = Path(config_root)
    if not root.exists():
        return ["PMU"]
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "coordinates.json").exists()
    )
    return names or ["PMU"]


def _fmt_optional_float(value: Optional[float]) -> str:
    if value is None:
        return "None"
    return f"{value:.1f}"


def _display_value(value: object) -> str:
    if value is None:
        return "---"
    return str(value)


def _display_percent(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return _display_value(value)


def _display_card(value: object) -> str:
    if value is None:
        return "--"
    return str(value)


def _decision_explanation(action: str, reason: str) -> str:
    explanations = {
        "new_party_pending_reset": "Nouvelle main detectee, attente du reset interne.",
        "hero_cards_not_detected_yet": "Cartes hero incompletes, pas de decision fiable.",
        "not_buttons": "Pas encore de bouton actif detecte.",
        "equity_not_ready": "Equity pas encore calculee.",
        "equity_required_not_ready": "Equity minimale pas encore calculee.",
        "free_option_strong_equity": "Option gratuite et main forte: relance proposee.",
        "free_option_no_call_needed": "Aucun montant a payer: check propose.",
        "negative_call_ev": "Call non rentable: fold propose.",
        "positive_edge_raise": "Relance proposee: equity nettement au-dessus de l'equity minimale.",
        "call_profitable_or_close": "Call rentable ou proche du seuil.",
    }
    detail = explanations.get(reason, reason)
    return f"{detail} ({reason})" if reason and detail != reason else detail


def _pad_list(values: list[object], size: int) -> list[object]:
    return list(values[:size]) + [None] * max(0, size - len(values))


def _style_card_label(label: tk.Label, value: object) -> None:
    text = _display_card(value)
    if text == "--":
        label.configure(bg="#f3f4f6", fg="#6b7280")
        return
    if "♥" in text or "♦" in text:
        label.configure(bg="#fff1f2", fg="#be123c")
        return
    if "♣" in text:
        label.configure(bg="#ecfdf5", fg="#047857")
        return
    if "♠" in text:
        label.configure(bg="#eff6ff", fg="#1d4ed8")
        return
    label.configure(bg="#ffffff", fg="#111827")


def _style_metric_label(label: Optional[tk.Label], value: object, *, positive_good: bool) -> None:
    if label is None:
        return
    number = _as_number(value)
    if number is None:
        label.configure(bg="#f3f4f6", fg="#374151")
        return
    good = number >= 0 if positive_good else number <= 0
    label.configure(
        bg="#dcfce7" if good else "#fee2e2",
        fg="#166534" if good else "#991b1b",
    )


def _style_equity_label(label: Optional[tk.Label], value: object) -> None:
    if label is None:
        return
    number = _as_number(value)
    if number is None:
        label.configure(bg="#f3f4f6", fg="#374151")
    elif number >= 0.55:
        label.configure(bg="#dcfce7", fg="#166534")
    elif number >= 0.35:
        label.configure(bg="#fef9c3", fg="#854d0e")
    else:
        label.configure(bg="#fee2e2", fg="#991b1b")


def _as_number(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _lighten_hex(color: str, amount: float) -> str:
    color = color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    red = min(255, int(red + (255 - red) * amount))
    green = min(255, int(green + (255 - green) * amount))
    blue = min(255, int(blue + (255 - blue) * amount))
    return f"#{red:02x}{green:02x}{blue:02x}"


if __name__ == "__main__":
    main()
