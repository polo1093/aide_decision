"""Tkinter tool-window actions for the main launcher app."""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from launch_support import (
    CONFIG_ROOT,
    PROJECT_ROOT,
    VIDEO_FILETYPES,
    _subprocess_creation_flags,
    build_capture_frames_args,
    build_identify_cards_args,
    build_interface_launch_command,
    build_quick_setup_args,
    build_validate_cards_args,
    build_zone_editor_args,
    format_command,
    script_path_for,
)
from objet.utils.logging_config import get_logger


logger = get_logger(__name__)


class AppToolsMixin:
    """Tool and calibration actions used by the Tkinter launcher."""

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
