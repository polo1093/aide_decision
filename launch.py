"""Interface Tkinter pour suivre le scan live et la decision."""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from objet.services.controller import Controller, ControllerViewState
from objet.utils.debug_capture import capture_blocking_error_screen
from objet.utils.logging_config import (
    configure_logging,
    get_logger,
    log_path_value,
    session_log,
)
from launch_support import (
    AUTO_CLICK_ARM_DELAY_SECONDS,
    AUTO_IDENTIFY_COOLDOWN_SECONDS,
    AUTO_CLICK_RETRY_SECONDS,
    CONFIG_ROOT,
    DEFAULT_GAME_NAME,
    DEFAULT_SCAN_INTERVAL_MS,
    DEFAULT_WINDOW_GEOMETRY,
    PROJECT_ROOT,
    TargetActionCommand,
    VIDEO_FILETYPES,
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
    _subprocess_creation_flags,
    _target_button_bbox,
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


class App(tk.Tk):
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
                "window_geometry": self.geometry(),
                "window_state": self.state(),
            }
        )

    def _current_game_name(self) -> str:
        return (self.var_game.get() or self.game_name or DEFAULT_GAME_NAME).strip()

    def _open_tools_window(self) -> None:
        if self._tools_window is not None and self._tools_window.winfo_exists():
            self._tools_window.lift()
            self._tools_window.focus_force()
            return

        window = tk.Toplevel(self)
        self._tools_window = window
        window.title("Outils")
        window.transient(self)
        window.resizable(False, False)

        def close_window() -> None:
            self._tools_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)

        body = ttk.Frame(window, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        tools_frame = ttk.LabelFrame(body, text="Outils", padding=8)
        tools_frame.grid(row=0, column=0, sticky="ew")
        tools_frame.grid_columnconfigure(0, weight=1)
        tools_frame.grid_columnconfigure(1, weight=1)

        tool_actions = [
            ("Remapping", self._open_quick_setup_dialog),
            ("Zones", self._run_zone_editor),
            ("Frames video", self._run_capture_frames),
            ("Identifier", self._run_identify_cards),
            ("Valider video", self._run_validate_cards),
            ("Clean histo", self._clear_player_history),
        ]
        for index, (label, command) in enumerate(tool_actions):
            ttk.Button(tools_frame, text=label, command=command).grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=6,
                pady=4,
            )

        ttk.Button(body, text="Fermer", command=close_window).grid(
            row=1,
            column=0,
            sticky="e",
            padx=6,
            pady=(10, 0),
        )

        window.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - window.winfo_width()) // 2)
        y = self.winfo_rooty() + 120
        window.geometry(f"+{x}+{y}")
        window.lift()
        window.focus_force()

    def _open_quick_setup_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Remapping cartes")
        dialog.transient(self)
        dialog.resizable(False, False)

        game_var = tk.StringVar(value=self._current_game_name())
        video_var = tk.StringVar(value="")
        edit_zones_var = tk.BooleanVar(value=True)
        extract_frames_var = tk.BooleanVar(value=True)
        identify_var = tk.BooleanVar(value=True)
        validate_var = tk.BooleanVar(value=True)

        body = ttk.Frame(dialog, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)

        ttk.Label(body, text="Jeu / profil").grid(row=0, column=0, sticky="w", pady=(0, 8))
        game_combo = ttk.Combobox(body, width=28, textvariable=game_var, values=self.game_profiles)
        game_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(body, text="Video OBS").grid(row=1, column=0, sticky="w", pady=(0, 8))
        video_entry = ttk.Entry(body, width=52, textvariable=video_var)
        video_entry.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(
            body,
            text="Parcourir",
            command=lambda: self._browse_video_into(video_var),
        ).grid(row=1, column=2, padx=(8, 0), pady=(0, 8))

        ttk.Checkbutton(body, text="Editer les zones", variable=edit_zones_var).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(body, text="Decouper la video en images", variable=extract_frames_var).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(body, text="Identifier / labelliser les cartes", variable=identify_var).grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(body, text="Valider la reconnaissance sur video", variable=validate_var).grid(row=5, column=0, columnspan=3, sticky="w", pady=(0, 10))

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e")
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="right")

        def run_setup() -> None:
            game = game_var.get().strip()
            if not game:
                messagebox.showerror("Jeu manquant", "Indique un nom de jeu/profil.")
                return

            args = build_quick_setup_args(
                game,
                config_root=CONFIG_ROOT,
                video=video_var.get().strip() or None,
                edit_zones=edit_zones_var.get(),
                extract_frames=extract_frames_var.get(),
                identify_cards=identify_var.get(),
                validate_video=validate_var.get(),
            )

            dialog.destroy()
            self._launch_script("quick_setup.py", args, label=f"remapping {game}")

        ttk.Button(buttons, text="Lancer", command=run_setup).pack(side="right", padx=(0, 8))

        dialog.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + 80
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()

    def _browse_video_into(self, var: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Choisir la video",
            filetypes=VIDEO_FILETYPES,
        )
        if selected:
            var.set(selected)

    def _run_zone_editor(self) -> None:
        game = self._current_game_name()
        self._launch_script("quick_setup.py", build_zone_editor_args(game), label=f"editeur zones {game}")

    def _run_capture_frames(self) -> None:
        game = self._current_game_name()
        video = self._ask_video()
        if not video:
            return
        self._launch_script(
            "Crop_Video_Frames.py",
            build_capture_frames_args(game, video),
            label=f"decoupe video {game}",
        )

    def _run_identify_cards(self) -> None:
        self._launch_identify_cards(auto=False)

    def _launch_identify_cards(self, *, auto: bool) -> Optional[subprocess.Popen]:
        game = self._current_game_name()
        label = f"identification cartes {game}"
        if auto:
            label = f"auto {label}"
        return self._launch_script(
            "identify_card.py",
            build_identify_cards_args(game),
            label=label,
            stop_scan=not auto,
        )

    def _run_validate_cards(self) -> None:
        game = self._current_game_name()
        video = self._ask_video()
        if not video:
            return
        self._launch_script(
            "capture_cards.py",
            build_validate_cards_args(game, video),
            label=f"validation cartes {game}",
        )

    def _clear_player_history(self) -> None:
        game = self._current_game_name()
        if not messagebox.askyesno(
            "Nettoyer historique",
            f"Supprimer l'historique long terme des joueurs pour {game} ?",
        ):
            return

        self.stop_scan()
        try:
            cleared_path = self.controller.clear_player_history()
        except Exception as exc:
            logger.exception("erreur nettoyage_historique_joueurs game=%s", game)
            messagebox.showerror("Nettoyage impossible", str(exc))
            return

        self._refresh_profile_status()
        self.var_notice.set(f"Historique joueurs vide pour {game}")
        self._set_text(f"Historique joueurs nettoye pour {game}\nFichier: {cleared_path}")

    def _ask_video(self) -> Optional[str]:
        selected = filedialog.askopenfilename(
            title="Choisir la video",
            filetypes=VIDEO_FILETYPES,
        )
        return selected or None

    def _launch_script(
        self,
        script_name: str,
        args: list[str],
        *,
        label: str,
        stop_scan: bool = True,
    ) -> Optional[subprocess.Popen]:
        try:
            script_path = script_path_for(script_name)
        except FileNotFoundError as exc:
            messagebox.showerror("Script introuvable", str(exc))
            return None

        if stop_scan:
            self.stop_scan()
        command = [sys.executable, str(script_path), *args]
        process_key = format_command(command)
        existing = self._tool_processes.get(process_key)
        if existing is not None and existing.poll() is None:
            self.var_notice.set(f"Outil deja ouvert: {label}")
            self._set_text(
                f"Outil deja ouvert: {label}\n"
                f"PID: {existing.pid}\n"
                "Ferme la fenetre de cet outil avant de le relancer."
            )
            return existing
        self._tool_processes.pop(process_key, None)

        launch_command = build_interface_launch_command(command, cwd=PROJECT_ROOT)
        try:
            process = subprocess.Popen(
                launch_command,
                cwd=str(PROJECT_ROOT),
                creationflags=_subprocess_creation_flags(),
            )
        except Exception as exc:
            logger.exception("erreur lancement_script script=%s args=%s", script_name, args)
            messagebox.showerror("Lancement impossible", str(exc))
            return None

        logger.info("lancement_script label=%s pid=%s command=%s", label, process.pid, launch_command)
        self._tool_processes[process_key] = process
        self.var_notice.set(f"Outil lance: {label}")
        self._set_text(f"Outil lance: {label}\nPID: {process.pid}\nCommande:\n{format_command(command)}")
        return process

    def start_scan(self) -> None:
        self._update_interval()
        if self.scanning:
            logger.info("scan_continu deja_actif interval_ms=%s", self.scan_interval_ms)
            return
        self.scanning = True
        self._last_tick_t = time.time()
        logger.info("debut scan_continu interval_ms=%s", self.scan_interval_ms)
        self.after(1, self._tick)

    def stop_scan(self) -> None:
        if self.scanning:
            logger.info("fin scan_continu last_ms=%s", _fmt_optional_float(self.last_call_ms))
        self.scanning = False
        self._stop_decision_blink()
        self._hide_button_highlight()

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

        if self._scan_in_flight:
            self._schedule_scan_poll()
            return

        self._scan_in_flight = True
        self.var_perf.set("scan: en cours | fps: " + (f"{self.fps:.1f}" if self.fps else "---"))
        thread = threading.Thread(
            target=self._run_controller_worker,
            name="scan-controller-worker",
            daemon=True,
        )
        thread.start()
        self._schedule_scan_poll()

    def _run_controller_worker(self) -> None:
        t0 = time.perf_counter()
        try:
            state = self.controller.run_cycle()
        except Exception as exc:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self._scan_result_queue.put(("error", exc, dt_ms))
            return
        dt_ms = (time.perf_counter() - t0) * 1000.0
        self._scan_result_queue.put(("ok", state, dt_ms))

    def _schedule_scan_poll(self) -> None:
        if self._scan_poll_after_id is None:
            self._scan_poll_after_id = self.after(25, self._poll_scan_result)

    def _poll_scan_result(self) -> None:
        self._scan_poll_after_id = None
        try:
            status, payload, dt_ms = self._scan_result_queue.get_nowait()
        except queue.Empty:
            if self._scan_in_flight:
                self._schedule_scan_poll()
            return

        self._scan_in_flight = False
        self.last_call_ms = dt_ms

        if status == "error":
            self.scanning = False
            error = payload if isinstance(payload, Exception) else RuntimeError(str(payload))
            self._handle_controller_exception(context="Scan continu", error=error)
            return

        if not self.scanning:
            return

        state = payload
        if not isinstance(state, ControllerViewState):
            self.scanning = False
            self._handle_controller_exception(
                context="Scan continu",
                error=TypeError(f"Etat de scan inattendu: {type(state)!r}"),
            )
            return
        self._apply_scan_result(state, dt_ms)

        if self.scanning:
            self._update_interval()
            next_delay = max(50, self.scan_interval_ms - int(dt_ms))
            self.after(next_delay, self._tick)

    def _apply_scan_result(self, state: ControllerViewState, dt_ms: float) -> None:
        self.last_call_ms = dt_ms

        now = time.time()
        if self._last_tick_t is not None:
            dt_s = max(now - self._last_tick_t, 1e-6)
            self.fps = 1.0 / dt_s
        else:
            self.fps = None
        self._last_tick_t = now

        self._apply_view_state(state)
        self._maybe_auto_identify_cards(state)
        fps_txt = f"{self.fps:.1f}" if self.fps else "---"
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: {fps_txt}")

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

    def _target_button_screen_bbox(self, target_button: Optional[dict[str, object]]) -> Optional[tuple[int, int, int, int]]:
        bbox = _target_button_bbox(target_button)
        if bbox is None:
            return None

        dx, dy = self._runtime_region_offset()
        x, y, width, height = bbox
        return x + dx, y + dy, width, height

    def _runtime_region_offset(self) -> tuple[int, int]:
        table = getattr(getattr(self.controller, "game", None), "table", None)
        scan = getattr(table, "scan", None)
        offset = getattr(scan, "runtime_region_offset", (0, 0))
        if not isinstance(offset, (list, tuple)) or len(offset) < 2:
            return 0, 0
        try:
            return int(round(float(offset[0]))), int(round(float(offset[1])))
        except (TypeError, ValueError):
            return 0, 0

    def _on_button_highlight_option_changed(self) -> None:
        if not self.var_show_button_highlight.get():
            self._hide_button_highlight()
            return

        state = getattr(self.controller, "last_view_state", None)
        if isinstance(state, ControllerViewState):
            self._update_button_highlight(state.target_button)

    def _toggle_auto_click(self) -> None:
        self.var_auto_click_target.set(not self.var_auto_click_target.get())
        self._on_auto_click_option_changed()

    def _on_auto_click_option_changed(self) -> None:
        if not self.var_auto_click_target.get():
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self._auto_click_ready_at = 0.0
            self._cancel_auto_click_timer()
            self._clear_pending_clicks()
            self.var_click_status.set("clic: off")
            return

        self._last_click_signature = None
        self._last_click_queued_at = 0.0
        self._auto_click_ready_at = time.monotonic() + AUTO_CLICK_ARM_DELAY_SECONDS
        self.var_click_status.set(f"clic: arme dans {AUTO_CLICK_ARM_DELAY_SECONDS:.1f}s")
        self._schedule_auto_click_ready_check(AUTO_CLICK_ARM_DELAY_SECONDS)

    def _maybe_queue_target_click(self, state: ControllerViewState) -> None:
        if not self.var_auto_click_target.get():
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self.var_click_status.set("clic: off")
            return

        wait_remaining = self._auto_click_wait_remaining()
        if wait_remaining > 0:
            self.var_click_status.set(f"clic: arme dans {wait_remaining:.1f}s")
            self._schedule_auto_click_ready_check(wait_remaining)
            return

        click_box = self._target_button_screen_bbox(state.target_button)
        if click_box is None:
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self.var_click_status.set("clic: pret")
            return

        if state.decision_action == "FOLD" and not self._fold_has_positive_call(state):
            self._last_click_signature = None
            self._last_click_queued_at = 0.0
            self.var_click_status.set("clic: fold bloque sans call")
            return

        signature = self._click_signature(state, click_box)
        now = time.monotonic()
        elapsed = now - self._last_click_queued_at
        if signature == self._last_click_signature and elapsed < AUTO_CLICK_RETRY_SECONDS:
            return

        self._last_click_signature = signature
        self._last_click_queued_at = now
        command = TargetActionCommand(
            click_box=click_box,
            game_name=state.game_name,
            decision_action=state.decision_action,
            raise_amount=self._target_raise_amount(state),
            runtime_offset=self._runtime_region_offset(),
        )
        self._click_queue.put(command)
        self.var_auto_click_target.set(False)
        self._last_click_signature = None
        self._last_click_queued_at = 0.0
        self._auto_click_ready_at = 0.0
        self._cancel_auto_click_timer()
        self.var_click_status.set(self._queued_click_status(command))

    def _click_signature(
        self,
        state: ControllerViewState,
        click_box: tuple[int, int, int, int],
    ) -> tuple[object, ...]:
        target = state.target_button or {}
        return (
            state.hand_id,
            state.decision_action,
            state.raise_amount,
            target.get("label"),
            target.get("state"),
            click_box,
        )

    def _click_worker_loop(self) -> None:
        while not self._click_worker_stop.is_set():
            try:
                command = self._click_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if command is None:
                continue
            try:
                self._execute_target_action(command)
            except Exception as exc:
                logger.exception("erreur_clic_bouton_cible command=%s", command)
                self.after(0, lambda exc=exc: self.var_click_status.set(f"clic: erreur {exc}"))
            else:
                self.after(0, lambda command=command: self.var_click_status.set(f"clic: fait {command.click_box}"))

    def _execute_target_action(self, command: TargetActionCommand) -> None:
        if command.decision_action == "RAISE" and command.raise_amount is not None:
            typed = enter_raise_amount_for_game(
                command.game_name,
                command.raise_amount,
                runtime_offset=command.runtime_offset,
            )
            if typed:
                logger.info(
                    "raise_amount_envoye game=%s amount=%s text=%s",
                    command.game_name,
                    command.raise_amount,
                    typed,
                )
        self._left_click_box_center(command.click_box)

    def _left_click_box_center(self, click_box: tuple[int, int, int, int]) -> None:
        x, y, width, height = click_box
        if width <= 0 or height <= 0:
            return

        click_target_button_box((x, y, width, height))

    def _target_raise_amount(self, state: ControllerViewState) -> Optional[float]:
        if state.decision_action != "RAISE":
            return None
        try:
            amount = float(state.raise_amount)
        except (TypeError, ValueError):
            return None
        return amount if amount > 0 else None

    def _fold_has_positive_call(self, state: ControllerViewState) -> bool:
        try:
            return float(state.to_call) > 0
        except (TypeError, ValueError):
            return False

    def _queued_click_status(self, command: TargetActionCommand) -> str:
        if command.decision_action == "RAISE" and command.raise_amount is not None:
            return f"clic: queue raise {command.raise_amount} {command.click_box} (one-shot)"
        return f"clic: queue {command.click_box} (one-shot)"

    def _stop_click_worker(self) -> None:
        self._click_worker_stop.set()
        self._click_queue.put(None)
        if self._click_worker.is_alive():
            self._click_worker.join(timeout=1.0)

    def _clear_pending_clicks(self) -> None:
        try:
            while True:
                self._click_queue.get_nowait()
        except queue.Empty:
            return

    def _auto_click_wait_remaining(self) -> float:
        ready_at = self.__dict__.get("_auto_click_ready_at", 0.0)
        if ready_at <= 0:
            return 0.0
        return max(0.0, ready_at - time.monotonic())

    def _schedule_auto_click_ready_check(self, delay_seconds: float) -> None:
        self._cancel_auto_click_timer()
        delay_ms = max(1, int(delay_seconds * 1000))
        self._auto_click_after_id = self.after(delay_ms, self._try_auto_click_current_state)

    def _cancel_auto_click_timer(self) -> None:
        after_id = self.__dict__.get("_auto_click_after_id")
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except Exception:
            pass
        self._auto_click_after_id = None

    def _try_auto_click_current_state(self) -> None:
        self._auto_click_after_id = None
        if not self.var_auto_click_target.get():
            return
        state = getattr(self.controller, "last_view_state", None)
        if isinstance(state, ControllerViewState):
            self._maybe_queue_target_click(state)
        else:
            self.var_click_status.set("clic: pret")

    def _register_click_hotkey(self) -> None:
        try:
            import keyboard

            self._click_hotkey = keyboard.add_hotkey(
                "f12",
                lambda: self.after(0, self._toggle_auto_click),
            )
        except Exception as exc:
            logger.warning("hotkey_f12_global_indisponible error=%s", exc)
            self._click_hotkey = None
            self.bind("<F12>", lambda _e: self._toggle_auto_click())

    def _unregister_click_hotkey(self) -> None:
        if self._click_hotkey is None:
            return
        try:
            import keyboard

            keyboard.remove_hotkey(self._click_hotkey)
        except Exception as exc:
            logger.warning("hotkey_f12_global_suppression_impossible error=%s", exc)
        self._click_hotkey = None

    def _show_button_highlight(self, bbox: tuple[int, int, int, int]) -> None:
        x, y, width, height = bbox
        if width <= 0 or height <= 0:
            self._hide_button_highlight()
            return

        color = "#ffd400"
        pad = 8
        thickness = 5
        segments = [
            (x - pad, y - pad, width + 2 * pad, thickness),
            (x - pad, y + height + pad - thickness, width + 2 * pad, thickness),
            (x - pad, y - pad, thickness, height + 2 * pad),
            (x + width + pad - thickness, y - pad, thickness, height + 2 * pad),
        ]

        windows = self._ensure_button_highlight_windows()
        for window, (sx, sy, sw, sh) in zip(windows, segments):
            window.configure(bg=color)
            window.geometry(f"{max(1, sw)}x{max(1, sh)}+{int(sx)}+{int(sy)}")
            window.deiconify()
            window.lift()

    def _ensure_button_highlight_windows(self) -> list[tk.Toplevel]:
        if self._button_highlight_windows:
            return self._button_highlight_windows

        for _ in range(4):
            window = tk.Toplevel(self)
            window.withdraw()
            window.overrideredirect(True)
            window.configure(bg="#ffd400")
            window.attributes("-topmost", True)
            self._button_highlight_windows.append(window)
        return self._button_highlight_windows

    def _hide_button_highlight(self) -> None:
        for window in self._button_highlight_windows:
            if window.winfo_exists():
                window.withdraw()

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


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="UI autour de Controller.run_cycle()")
    parser.add_argument("--interval", type=int, default=DEFAULT_SCAN_INTERVAL_MS, help="Intervalle entre deux scans en ms (minimum 25)")
    parser.add_argument("--game", help="Nom du jeu/profil dans config/ (sinon dernier profil utilise)")
    parser.add_argument("--list-games", action="store_true", help="Liste les profils disponibles puis quitte.")
    parser.add_argument("--snapshot", action="store_true", help="Execute un seul scan dans le terminal.")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.list_games:
        for name in available_game_names():
            print(name)
        return

    interface_state = load_interface_state()
    initial_game = select_initial_game(args.game, interface_state, available_game_names())

    configure_logging()
    with session_log("interface") as log_file:
        logger.info(
            "debut interface interval_ms=%s game=%s log=%s",
            args.interval,
            initial_game,
            log_path_value(log_file),
        )
        controller = Controller(
            game_name=initial_game,
            coord_path=CONFIG_ROOT / initial_game / "coordinates.json",
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
