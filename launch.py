"""Interface Tkinter pour suivre le scan live et la decision."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

from launcher.app_tools import AppToolsMixin
from launcher.cli import (
    DECISION_MODES,
    DEFAULT_HERO_POSITION,
    parse_args,
    select_initial_decision_mode,
    select_initial_hero_position,
)
from launcher.clicks import AppClickMixin
from launcher.scan_loop import AppScanMixin
from objet.services.controller import Controller, ControllerViewState
from objet.services.decision import Decision
from objet.services.range_analyzer import POSITIONS as HERO_POSITIONS
from objet.utils.debug_capture import capture_blocking_error_screen
from objet.utils.logging_config import (
    configure_logging,
    get_logger,
    log_path_value,
    session_log,
)
from launch_support import (
    AUTO_IDENTIFY_COOLDOWN_SECONDS,
    CONFIG_ROOT,
    DEFAULT_GAME_NAME,
    DEFAULT_SCAN_INTERVAL_MS,
    DEFAULT_WINDOW_GEOMETRY,
    TargetActionCommand,
    ProfileItem,
    _decision_explanation,
    _display_card,
    _display_percent,
    _display_value,
    _fmt_optional_float,
    _lighten_hex,
    _pad_list,
    _state_text,
    _style_card_label,
    _style_equity_label,
    _style_metric_label,
    available_game_names,
    build_capture_frames_args,
    build_identify_cards_args,
    build_interface_launch_command,
    build_quick_setup_args,
    build_validate_cards_args,
    build_zone_editor_args,
    click_target_button_box,
    enter_raise_amount_for_game,
    format_command,
    load_interface_state,
    needs_card_identification,
    normalise_game_name,
    normalise_scan_interval_ms,
    profile_status,
    save_interface_state,
    script_path_for,
    select_initial_game,
)


logger = get_logger(__name__)


class App(AppToolsMixin, AppClickMixin, AppScanMixin, tk.Tk):
    def __init__(
        self,
        controller: Controller,
        scan_interval_ms: int = DEFAULT_SCAN_INTERVAL_MS,
        game_name: str = DEFAULT_GAME_NAME,
        *,
        window_geometry: Optional[str] = None,
        window_state: Optional[str] = None,
    ):
        super().__init__()

        self.title("Aide decision - table live")
        self.geometry(window_geometry or DEFAULT_WINDOW_GEOMETRY)
        self.minsize(960, 640)

        self.controller = controller
        self.game_name = game_name
        decision_config = getattr(getattr(controller, "decision", None), "config", None)
        self.decision_mode = getattr(decision_config, "mode", "legacy")
        self.hero_position = getattr(controller, "hero_position", DEFAULT_HERO_POSITION)
        self.game_profiles = available_game_names()

        self.scanning = False
        self.scan_interval_ms = normalise_scan_interval_ms(scan_interval_ms)
        self._last_tick_t: Optional[float] = None
        self._scan_in_flight = False
        self._scan_result_queue: "queue.Queue[tuple[str, object, float]]" = queue.Queue()
        self._scan_poll_after_id: Optional[str] = None
        self._click_queue: "queue.Queue[Optional[TargetActionCommand]]" = queue.Queue()
        self._click_worker_stop = threading.Event()
        self._click_worker = threading.Thread(
            target=self._click_worker_loop,
            name="target-button-click-worker",
            daemon=True,
        )
        self._click_hotkey = None
        self._last_click_signature: Optional[tuple[object, ...]] = None
        self._last_click_queued_at = 0.0
        self._auto_click_ready_at = 0.0
        self._auto_click_after_id: Optional[str] = None
        self._tool_processes: dict[str, subprocess.Popen] = {}
        self._last_auto_identify_t = 0.0
        self._tools_window: Optional[tk.Toplevel] = None
        self._live_card_prompt_open = False
        self._live_card_identifier = None
        self._live_card_identifier_game: Optional[str] = None

        self.last_call_ms: Optional[float] = None
        self.fps: Optional[float] = None
        self._blink_after_id: Optional[str] = None
        self._blink_on = False
        self._base_decision_color = "#6c757d"
        self._button_highlight_windows: list[tk.Toplevel] = []

        self.metric_vars: dict[str, tk.StringVar] = {}
        self.metric_value_labels: dict[str, tk.Label] = {}
        self.summary_value_labels: dict[str, tk.Label] = {}
        self.profile_labels: list[tk.Label] = []
        self.var_auto_identify_cards = tk.BooleanVar(value=False)
        self.var_show_button_highlight = tk.BooleanVar(value=True)
        self.var_auto_click_target = tk.BooleanVar(value=False)
        self.var_click_status = tk.StringVar(value="clic: off")

        self._build()
        self._build_menu()
        self._layout()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._click_worker.start()
        self._register_click_hotkey()
        if window_state == "zoomed":
            self.after(0, lambda: self.state("zoomed"))
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
        self.lbl_decision_mode = ttk.Label(self.frm_top, text="Mode decision")
        self.var_decision_mode = tk.StringVar(value=self.decision_mode)
        self.cmb_decision_mode = ttk.Combobox(
            self.frm_top,
            width=12,
            textvariable=self.var_decision_mode,
            values=DECISION_MODES,
            state="readonly",
        )
        self.lbl_hero_position = ttk.Label(self.frm_top, text="Position auto")
        self.var_hero_position = tk.StringVar(value=self.hero_position)
        self.cmb_hero_position = ttk.Combobox(
            self.frm_top,
            width=5,
            textvariable=self.var_hero_position,
            values=HERO_POSITIONS,
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
        self.btn_tools = ttk.Button(self.frm_side, text="Outils", command=self._open_tools_window)
        self.frm_options = ttk.LabelFrame(self.frm_side, text="Options")
        self.chk_auto_identify_cards = ttk.Checkbutton(
            self.frm_options,
            text="Demander carte non lue (live, 5s)",
            variable=self.var_auto_identify_cards,
        )
        self.chk_show_button_highlight = ttk.Checkbutton(
            self.frm_options,
            text="Afficher rectangle bouton cible",
            variable=self.var_show_button_highlight,
            command=self._on_button_highlight_option_changed,
        )
        self.chk_auto_click_target = ttk.Checkbutton(
            self.frm_options,
            text="Cliquer bouton cible (F12)",
            variable=self.var_auto_click_target,
            command=self._on_auto_click_option_changed,
        )
        self.lbl_click_status = ttk.Label(self.frm_options, textvariable=self.var_click_status)
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

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        tools = tk.Menu(menubar, tearoff=False)
        tools.add_command(
            label="Ouvrir la fenetre outils",
            command=self._open_tools_window,
        )
        tools.add_separator()
        tools.add_command(
            label="Nouveau jeu / remapping cartes...",
            command=self._open_quick_setup_dialog,
        )
        tools.add_separator()
        tools.add_command(label="Editer les zones", command=self._run_zone_editor)
        tools.add_command(label="Decouper une video en images...", command=self._run_capture_frames)
        tools.add_command(label="Identifier / labelliser les cartes", command=self._run_identify_cards)
        tools.add_command(label="Valider le scan cartes sur video...", command=self._run_validate_cards)
        tools.add_separator()
        tools.add_command(label="Nettoyer historique joueurs", command=self._clear_player_history)

        menubar.add_cascade(label="Outils", menu=tools)
        self.configure(menu=menubar)

    def _layout(self) -> None:
        self.frm_top.pack(side="top", fill="x", padx=10, pady=8)
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_stop.pack(side="left", padx=(0, 6))
        self.btn_snap.pack(side="left", padx=(0, 16))
        self.lbl_game.pack(side="left")
        self.cmb_game.pack(side="left", padx=(6, 14))
        self.lbl_decision_mode.pack(side="left")
        self.cmb_decision_mode.pack(side="left", padx=(6, 14))
        self.lbl_hero_position.pack(side="left")
        self.cmb_hero_position.pack(side="left", padx=(6, 14))
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
        self.btn_tools.pack(side="top", fill="x", pady=(0, 8))
        self.frm_options.pack(side="top", fill="x", pady=(0, 8))
        self.chk_auto_identify_cards.pack(side="top", anchor="w", padx=12, pady=(10, 4))
        self.chk_show_button_highlight.pack(side="top", anchor="w", padx=12, pady=(0, 4))
        self.chk_auto_click_target.pack(side="top", anchor="w", padx=12, pady=(0, 4))
        self.lbl_click_status.pack(side="top", anchor="w", padx=12, pady=(0, 10))
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
        self.ent_interval.bind("<FocusOut>", lambda _e: self._update_interval())
        self.cmb_game.bind("<<ComboboxSelected>>", lambda _e: self._switch_game())
        self.cmb_decision_mode.bind("<<ComboboxSelected>>", lambda _e: self._switch_decision_mode())
        self.cmb_hero_position.bind("<<ComboboxSelected>>", lambda _e: self._switch_hero_position())

    def _apply_empty_state(self) -> None:
        self.var_scan.set("pret")
        self.var_hand.set("---")
        self.var_street.set("---")
        self.var_action_available.set("---")
        self.var_notice.set("")
        self.var_players.set("")
        self.var_buttons.set("")
        self._hide_button_highlight()
        self._set_text("")

    def _set_text(self, text: str) -> None:
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self.txt.configure(state="disabled")

    def _update_interval(self) -> None:
        self.scan_interval_ms = normalise_scan_interval_ms(
            self.var_interval.get(),
            fallback=self.scan_interval_ms,
        )
        self.var_interval.set(str(self.scan_interval_ms))

    def _switch_game(self) -> None:
        selected = self.var_game.get().strip()
        if not selected or selected == self.game_name:
            return

        self.stop_scan()
        logger.info("changement_jeu old=%s new=%s", self.game_name, selected)
        try:
            self.controller = Controller(
                game_name=selected,
                coord_path=CONFIG_ROOT / selected / "coordinates.json",
                decision_mode=self.decision_mode,
                hero_position=self.hero_position,
            )
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
        self._save_interface_state()
        self._last_auto_identify_t = 0.0

    def _switch_decision_mode(self) -> None:
        selected = self.var_decision_mode.get().strip()
        if selected not in DECISION_MODES:
            self.var_decision_mode.set(self.decision_mode)
            return
        if selected == self.decision_mode:
            return

        self.stop_scan()
        logger.info("changement_mode_decision old=%s new=%s game=%s", self.decision_mode, selected, self.game_name)
        self.controller.decision = Decision(mode=selected)
        self.decision_mode = selected
        self._save_interface_state()

    def _switch_hero_position(self) -> None:
        selected = self.var_hero_position.get().strip().upper()
        if selected not in HERO_POSITIONS:
            self.var_hero_position.set(self.hero_position)
            return
        if selected == self.hero_position:
            return

        logger.info("changement_position_fallback old=%s new=%s game=%s", self.hero_position, selected, self.game_name)
        self.controller.set_hero_position(selected)
        self.hero_position = selected
        self._save_interface_state()

    def _on_close(self) -> None:
        self.stop_scan()
        self._unregister_click_hotkey()
        self._stop_click_worker()
        self._save_interface_state()
        self.destroy()

    def _save_interface_state(self) -> None:
        save_interface_state(
            {
                "game_name": self._current_game_name(),
                "decision_mode": self.decision_mode,
                "hero_position": self.hero_position,
                "window_geometry": self.geometry(),
                "window_state": self.state(),
            }
        )

    def _current_game_name(self) -> str:
        return (self.var_game.get() or self.game_name or DEFAULT_GAME_NAME).strip()

    def _maybe_auto_identify_cards(self, state: ControllerViewState) -> None:
        if not self.var_auto_identify_cards.get():
            return
        if not needs_card_identification(state):
            return
        if self._live_card_prompt_open:
            return

        now = time.monotonic()
        elapsed = now - self._last_auto_identify_t
        if elapsed < AUTO_IDENTIFY_COOLDOWN_SECONDS:
            logger.debug(
                "SKIP auto_identification_cartes raison=cooldown elapsed=%.2f",
                elapsed,
            )
            return

        if self._prompt_live_unread_card(state):
            self._last_auto_identify_t = now

    def _prompt_live_unread_card(self, state: ControllerViewState) -> bool:
        candidate = self._find_live_unread_card(state)
        if candidate is None:
            logger.debug("SKIP identification_live_cartes raison=aucune_carte_visible_non_lue")
            return False

        base_key, card, number_patch, suit_patch = candidate
        self._live_card_prompt_open = True
        try:
            identifier = self._get_live_card_identifier()
            result = identifier.identify_from_patches(
                number_patch,
                suit_patch,
                base_key=base_key,
                template_set=getattr(card, "template_set", None),
                interactive=True,
                force_all=False,
                parent=self,
            )
        except Exception as exc:
            self._handle_controller_exception(context=f"Identification live {base_key}", error=exc)
            return True
        finally:
            self._live_card_prompt_open = False

        source = str(result.meta.get("source", ""))
        if source == "delete":
            self.var_notice.set("Delete ignore en mode live: aucune capture d'entrainement a supprimer.")
            logger.info("identification_live_cartes delete_ignore base_key=%s", base_key)
            return True

        if result.number not in ("", "?") or result.suit not in ("", "?"):
            number = result.number if result.number not in ("", "?") else getattr(card, "value", None)
            suit = result.suit if result.suit not in ("", "?") else getattr(card, "suit", None)
            card.apply_observation(number, suit)

        self._reload_scan_card_templates()
        self.var_notice.set(f"Carte live traitee: {base_key} ({source or 'inconnu'})")
        logger.info(
            "identification_live_cartes base_key=%s source=%s number=%s suit=%s",
            base_key,
            source,
            result.number,
            result.suit,
        )
        return True

    def _get_live_card_identifier(self):
        game = self._current_game_name()
        if self._live_card_identifier is not None and self._live_card_identifier_game == game:
            return self._live_card_identifier

        from objet.services.card_identifier import CardIdentifier

        self._live_card_identifier = CardIdentifier(CONFIG_ROOT / game)
        self._live_card_identifier_game = game
        return self._live_card_identifier

    def _find_live_unread_card(self, state: ControllerViewState):
        if not state.scan_ok:
            return None

        scan = getattr(getattr(self.controller.game, "table", None), "scan", None)
        if scan is None or getattr(scan, "screen_array", None) is None:
            return None

        for base_key, card in self._iter_live_card_slots(state):
            if getattr(card, "formatted", None):
                continue
            number_box = getattr(card, "card_coordinates_value", None)
            suit_box = getattr(card, "card_coordinates_suit", None)
            if not number_box or not suit_box:
                continue

            number_patch_raw = scan._extract_patch(number_box, pad=3)
            suit_patch_raw = scan._extract_patch(suit_box, pad=3)
            if self._live_card_patch_is_hand_overlay(scan, card, number_patch_raw):
                continue
            if not self._live_card_patch_present(number_patch_raw):
                continue

            return (
                base_key,
                card,
                self._bgr_patch_to_pil(number_patch_raw),
                self._bgr_patch_to_pil(suit_patch_raw),
            )
        return None

    def _iter_live_card_slots(self, state: ControllerViewState):
        cards = getattr(getattr(self.controller.game, "table", None), "cards", None)
        if cards is None:
            return

        for index, card in enumerate(cards.me_cards(), start=1):
            yield f"player_card_{index}", card

        street = str(state.street or "").upper()
        expected_board_count = {"FLOP": 3, "TURN": 4, "RIVER": 5}.get(street, 0)
        for index, card in enumerate(cards.board_cards()[:expected_board_count], start=1):
            yield f"board_card_{index}", card

    def _live_card_patch_present(self, number_patch) -> bool:
        from objet.services.card_identifier import is_card_present

        return bool(is_card_present(number_patch, threshold=215, min_ratio=0.04))

    def _live_card_patch_is_hand_overlay(self, scan, card, number_patch) -> bool:
        template_set = str(getattr(card, "template_set", "") or "").lower()
        if "hand" not in template_set:
            return False
        should_skip = getattr(scan, "_should_skip_for_fold", None)
        if should_skip is None:
            return False
        try:
            return bool(should_skip(number_patch))
        except Exception:
            return False

    def _bgr_patch_to_pil(self, patch):
        import cv2
        from PIL import Image

        if len(getattr(patch, "shape", ())) == 2:
            return Image.fromarray(patch)
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def _reload_scan_card_templates(self) -> None:
        scan = getattr(getattr(self.controller.game, "table", None), "scan", None)
        template_index = getattr(scan, "template_index", None)
        if template_index is None:
            return
        try:
            template_index.load()
        except Exception as exc:
            logger.warning("rechargement_templates_scan_impossible error=%s", exc)

    def _is_tool_running(self, script_name: str, args: list[str]) -> bool:
        try:
            script_path = script_path_for(script_name)
        except FileNotFoundError:
            return False
        command = [sys.executable, str(script_path), *args]
        process_key = format_command(command)
        existing = self._tool_processes.get(process_key)
        if existing is None:
            return False
        if existing.poll() is None:
            return True
        self._tool_processes.pop(process_key, None)
        return False

    def _apply_view_state(self, state: ControllerViewState) -> None:
        self.var_scan.set("OK" if state.scan_ok else f"table absente ({state.scan_failures})")
        self.var_hand.set(_display_value(state.hand_id))
        self.var_street.set(state.street)
        if state.hero_position in HERO_POSITIONS:
            self.hero_position = state.hero_position
            self.var_hero_position.set(state.hero_position)
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
        self._update_button_highlight(state.target_button)
        self._maybe_queue_target_click(state)
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

    def _update_button_highlight(self, target_button: Optional[dict[str, object]]) -> None:
        if not self.var_show_button_highlight.get():
            self._hide_button_highlight()
            return

        bbox = self._target_button_screen_bbox(target_button)
        if bbox is None:
            self._hide_button_highlight()
            return
        self._show_button_highlight(bbox)

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


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.list_games:
        for name in available_game_names():
            print(name)
        return

    interface_state = load_interface_state()
    initial_game = select_initial_game(args.game, interface_state, available_game_names())
    initial_decision_mode = select_initial_decision_mode(
        args.decision_mode,
        interface_state,
        cli_explicit=args.decision_mode_explicit,
    )
    initial_hero_position = select_initial_hero_position(
        args.hero_position,
        interface_state,
        cli_explicit=args.hero_position_explicit,
    )

    configure_logging()
    with session_log("interface") as log_file:
        logger.info(
            "debut interface interval_ms=%s game=%s decision_mode=%s hero_position=%s log=%s",
            args.interval,
            initial_game,
            initial_decision_mode,
            initial_hero_position,
            log_path_value(log_file),
        )
        controller = Controller(
            game_name=initial_game,
            coord_path=CONFIG_ROOT / initial_game / "coordinates.json",
            decision_mode=initial_decision_mode,
            hero_position=initial_hero_position,
        )
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

        app = App(
            controller=controller,
            scan_interval_ms=args.interval,
            game_name=initial_game,
            window_geometry=_state_text(interface_state, "window_geometry"),
            window_state=_state_text(interface_state, "window_state"),
        )
        app.mainloop()
        logger.info("fin interface status=closed log=%s", log_path_value(log_file))


if __name__ == "__main__":
    main()
