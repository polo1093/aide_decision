"""Interface Tkinter pour suivre le scan live et la decision."""

from __future__ import annotations

import argparse
import json
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from objet.services.controller import Controller, ControllerViewState
from objet.services.player_history import DEFAULT_PLAYER_HISTORY_DIR, player_history_path
from objet.utils.debug_capture import capture_blocking_error_screen
from objet.utils.logging_config import (
    configure_logging,
    get_logger,
    log_path_value,
    session_log,
)


logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_ROOT = PROJECT_ROOT / "config"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
INTERFACE_STATE_PATH = CONFIG_ROOT / "_interface_state.json"
DEFAULT_GAME_NAME = "PMU"
DEFAULT_WINDOW_GEOMETRY = "1080x760"
VIDEO_FILETYPES = (
    ("Videos", "*.avi *.mp4 *.mkv *.mov"),
    ("Tous les fichiers", "*.*"),
)


class App(tk.Tk):
    def __init__(
        self,
        controller: Controller,
        scan_interval_ms: int = 1000,
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
        self.scan_interval_ms = scan_interval_ms
        self._last_tick_t: Optional[float] = None
        self._scan_in_flight = False
        self._scan_result_queue: "queue.Queue[tuple[str, object, float]]" = queue.Queue()
        self._scan_poll_after_id: Optional[str] = None
        self._tool_processes: dict[str, subprocess.Popen] = {}

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

        self._build()
        self._build_menu()
        self._layout()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
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
        self.frm_tools = ttk.LabelFrame(self.frm_side, text="Outils")
        self.tool_buttons = [
            ttk.Button(self.frm_tools, text="Remapping", command=self._open_quick_setup_dialog),
            ttk.Button(self.frm_tools, text="Zones", command=self._run_zone_editor),
            ttk.Button(self.frm_tools, text="Frames video", command=self._run_capture_frames),
            ttk.Button(self.frm_tools, text="Identifier", command=self._run_identify_cards),
            ttk.Button(self.frm_tools, text="Valider video", command=self._run_validate_cards),
            ttk.Button(self.frm_tools, text="Clean histo", command=self._clear_player_history),
        ]
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
        self.frm_tools.pack(side="top", fill="x", pady=(0, 8))
        self.frm_players.pack(side="top", fill="both", expand=True, pady=(0, 8))
        self.frm_buttons.pack(side="top", fill="x")
        for index, button in enumerate(self.tool_buttons):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=8, pady=4)
        self.frm_tools.grid_columnconfigure(0, weight=1)
        self.frm_tools.grid_columnconfigure(1, weight=1)
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
        self._hide_button_highlight()
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

    def _on_close(self) -> None:
        self.stop_scan()
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
        game = self._current_game_name()
        self._launch_script("identify_card.py", build_identify_cards_args(game), label=f"identification cartes {game}")

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

    def _launch_script(self, script_name: str, args: list[str], *, label: str) -> Optional[subprocess.Popen]:
        try:
            script_path = script_path_for(script_name)
        except FileNotFoundError as exc:
            messagebox.showerror("Script introuvable", str(exc))
            return None

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
        fps_txt = f"{self.fps:.1f}" if self.fps else "---"
        self.var_perf.set(f"scan: {dt_ms:.1f} ms | fps: {fps_txt}")

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
        bbox = _target_button_bbox(target_button)
        if bbox is None:
            self._hide_button_highlight()
            return
        self._show_button_highlight(bbox)

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


class ProfileItem:
    def __init__(self, label: str, ok: bool, detail: str) -> None:
        self.label = label
        self.ok = ok
        self.detail = detail


def profile_status(
    game_name: str,
    config_root: Path | str = CONFIG_ROOT,
    history_root: Path | str = DEFAULT_PLAYER_HISTORY_DIR,
) -> list[ProfileItem]:
    game_dir = Path(config_root) / game_name
    action_files = ["check.png", "paie.png", "relance.png", "fold.png", "sit_out.png", "play.png"]
    cards_dir = game_dir / "Cards"
    cards_png = list(cards_dir.rglob("*.png")) if cards_dir.exists() else []
    history_item = _history_profile_item(game_name, history_root=history_root)
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
        history_item,
    ]


def _profile_item(label: str, path: Path, detail: str) -> ProfileItem:
    return ProfileItem(label, path.exists(), detail if path.exists() else "manquant")


def _history_profile_item(game_name: str, *, history_root: Path | str) -> ProfileItem:
    path = player_history_path(game_name, root_dir=history_root)
    if not path.exists():
        return ProfileItem("Historique", True, "0 joueur")
    try:
        import json

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        players = data.get("players", {}) if isinstance(data, dict) else {}
        count = len(players) if isinstance(players, dict) else 0
    except Exception:
        return ProfileItem("Historique", False, "illisible")
    return ProfileItem("Historique", True, f"{count} joueur(s)")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="UI autour de Controller.run_cycle()")
    parser.add_argument("--interval", type=int, default=1000, help="Intervalle entre deux scans en ms (25..2000)")
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


def available_game_names(config_root: Path | str = CONFIG_ROOT) -> list[str]:
    root = Path(config_root)
    if not root.exists():
        return [DEFAULT_GAME_NAME]
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "coordinates.json").exists()
    )
    return names or [DEFAULT_GAME_NAME]


def load_interface_state(path: Path | str = INTERFACE_STATE_PATH) -> dict[str, object]:
    state_path = Path(path)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("interface_state_lecture_impossible path=%s error=%s", state_path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def save_interface_state(state: dict[str, object], path: Path | str = INTERFACE_STATE_PATH) -> None:
    state_path = Path(path)
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("interface_state_ecriture_impossible path=%s error=%s", state_path, exc)


def select_initial_game(cli_game: Optional[str], state: dict[str, object], profiles: list[str]) -> str:
    candidates: list[str] = []
    if cli_game:
        candidates.append(cli_game)
    saved_game = _state_text(state, "game_name")
    if saved_game:
        candidates.append(saved_game)
    candidates.append(DEFAULT_GAME_NAME)
    candidates.extend(profiles)

    for candidate in candidates:
        game = candidate.strip()
        if game and game in profiles:
            return game
    return DEFAULT_GAME_NAME


def _state_text(state: dict[str, object], key: str) -> Optional[str]:
    value = state.get(key)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def normalise_game_name(game_name: str) -> str:
    game = str(game_name).strip()
    if not game:
        raise ValueError("game_name is required")
    return game


def build_quick_setup_args(
    game_name: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
    video: Optional[str] = None,
    edit_zones: bool = True,
    extract_frames: bool = True,
    identify_cards: bool = True,
    validate_video: bool = True,
) -> list[str]:
    args = ["--game", normalise_game_name(game_name), "--config-root", str(Path(config_root))]
    if video:
        args += ["--video", str(video)]
    if not edit_zones:
        args.append("--skip-zone-editor")
    if not extract_frames:
        args.append("--skip-capture")
    if not identify_cards:
        args.append("--skip-identify")
    if not validate_video:
        args.append("--skip-capture-validation")
    return args


def build_zone_editor_args(game_name: str, *, config_root: Path | str = CONFIG_ROOT) -> list[str]:
    return build_quick_setup_args(
        game_name,
        config_root=config_root,
        extract_frames=False,
        identify_cards=False,
        validate_video=False,
    )


def build_capture_frames_args(
    game_name: str,
    video: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
) -> list[str]:
    game_dir = Path(config_root) / normalise_game_name(game_name)
    return ["--game-dir", str(game_dir), "--video", str(video)]


def build_identify_cards_args(game_name: str) -> list[str]:
    return ["--game", normalise_game_name(game_name)]


def build_validate_cards_args(
    game_name: str,
    video: str,
    *,
    config_root: Path | str = CONFIG_ROOT,
) -> list[str]:
    game = normalise_game_name(game_name)
    game_dir = Path(config_root) / game
    return ["--game", game, "--game-dir", str(game_dir), "--video", str(video)]


def script_path_for(script_name: str) -> Path:
    path = SCRIPTS_ROOT / script_name
    if not path.is_file():
        raise FileNotFoundError(f"{path} n'existe pas.")
    return path


def _subprocess_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if sys.platform.startswith("win") else 0


def build_interface_launch_command(
    command: list[str],
    *,
    cwd: Path | str = PROJECT_ROOT,
    launcher_dir: Path | str | None = None,
) -> list[str]:
    if not sys.platform.startswith("win"):
        return command
    launcher_root = Path(launcher_dir) if launcher_dir is not None else PROJECT_ROOT / "logs" / "tool_launchers"
    launcher_root.mkdir(parents=True, exist_ok=True)
    launcher_path = launcher_root / f"tool_{int(time.time() * 1000)}_{abs(hash(tuple(command))) & 0xffff:x}.cmd"
    command_line = subprocess.list2cmdline([str(part) for part in command])
    launcher_path.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'cd /d "{Path(cwd)}"',
                command_line,
                "set tool_exit=%ERRORLEVEL%",
                "echo.",
                "echo Termine avec code %tool_exit% . Appuie sur une touche pour fermer cette fenetre.",
                "pause >nul",
                "exit /b %tool_exit%",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ["cmd.exe", "/C", str(launcher_path)]


def format_command(command: list[str]) -> str:
    return " ".join(_quote_command_part(part) for part in command)


def _quote_command_part(part: str) -> str:
    text = str(part)
    if any(char.isspace() for char in text):
        return f'"{text}"'
    return text


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


def _target_button_bbox(target_button: Optional[dict[str, object]]) -> Optional[tuple[int, int, int, int]]:
    if not target_button:
        return None
    bbox = target_button.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    return tuple(int(value) for value in bbox)


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
