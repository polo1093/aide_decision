# position_zones_ctk.py — UI simplifiée pour éditer les zones
# UI uniquement — la logique métier est dans zone_project.py

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple, List

import tkinter as tk
from tkinter import filedialog  # plus utilisé pour le save-as, mais on garde l'import

import customtkinter as ctk
from PIL import ImageTk, Image

# =========================
# Constantes "en dur"
# =========================
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DEFAULT_GAME_NAME = "PMU"
DEFAULT_IMAGE_NAME = "example_full_screen.png"

# Chemin projet pour les imports
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from objet.services.game import Game
from zone_project import ZoneProject

APP_TITLE = "Zone Editor (CustomTkinter)"


class ZoneEditorCTK:
    def __init__(self, base_dir: Optional[str] = None):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(APP_TITLE)

        # Plein écran ancré en (0, 0)
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")

        # Fermeture : aucune sauvegarde automatique
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Modèle
        self.base_dir = os.path.abspath(base_dir or str(DEFAULT_CONFIG_DIR))
        self.project = ZoneProject(Game.for_script(Path(__file__).name))

        # Image affichée
        self.tk_img: Optional[ImageTk.PhotoImage] = None
        self.base_scale: float = 1.0
        self.user_zoom: float = 0.85  # zoom par défaut
        self.scale: float = 1.0

        # Dessin
        self.rect_items: dict[str, int] = {}
        self.text_items: dict[str, int] = {}
        self.dragging_key: Optional[str] = None
        self.drag_offset: Tuple[int, int] = (0, 0)
        self._last_key: Optional[str] = None

        self._build_ui()
        self._bind_canvas_events()
        self._refresh_games_list()

    # ---------- UI ----------
    def _build_ui(self):
        # Topbar
        top = ctk.CTkFrame(self.root, corner_radius=0)
        top.pack(side="top", fill="x")

        # Jeux
        ctk.CTkLabel(top, text="Jeu:").pack(side="left", padx=(8, 4), pady=8)
        self.game_var = tk.StringVar(value="")
        self.game_menu = ctk.CTkOptionMenu(
            top, values=[""], variable=self.game_var, command=self._on_select_game
        )
        self.game_menu.pack(side="left", padx=4, pady=8)

        # Zoom
        ctk.CTkLabel(top, text="Zoom").pack(side="left", padx=(16, 4))
        self.zoom_slider = ctk.CTkSlider(
            top,
            from_=0.25,
            to=3.0,
            number_of_steps=55,
            command=lambda v: self._on_zoom_slider(float(v)),
        )
        self.zoom_slider.set(self.user_zoom)
        self.zoom_slider.pack(side="left", padx=6, pady=8)
        self.zoom_pct_label = ctk.CTkLabel(top, text="85%")
        self.zoom_pct_label.pack(side="left", padx=(6, 2))

        # Bouton "Ajuster" → remet à 85 %
        self.btn_adjust = ctk.CTkButton(
            top, text="Ajuster", width=80, command=self._zoom_85
        )
        self.btn_adjust.pack(side="left", padx=4, pady=8)

        # Enregistrer
        self.btn_save = ctk.CTkButton(
            top, text="Enregistrer", command=self._save_json, state="disabled"
        )
        self.btn_save.pack(side="left", padx=8, pady=8)

        # Main split
        main = ctk.CTkFrame(self.root)
        main.pack(side="top", fill="both", expand=True)

        # Canvas (zone d'image)
        cf = ctk.CTkFrame(main)
        cf.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)
        self.canvas = tk.Canvas(
            cf,
            bg="#F2F2F2",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        # Sidebar (toujours visible)
        side = ctk.CTkFrame(main, width=360)
        side.pack(side="right", fill="y", padx=(5, 10), pady=10)

        ctk.CTkLabel(
            side, text="Régions", font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 6))
        self.listbox = tk.Listbox(side, height=14, exportselection=False)
        self.listbox.pack(fill="x", padx=12)
        self.listbox.bind("<<ListboxSelect>>", self._on_select_region_from_list)

        frm = ctk.CTkFrame(side)
        frm.pack(fill="x", padx=12, pady=12)

        ctk.CTkLabel(frm, text="Nom (clé)").grid(row=0, column=0, sticky="w")
        self.entry_name = ctk.CTkEntry(frm)
        self.entry_name.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        frm.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frm, text="Groupe").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.group_var = tk.StringVar(value="")
        self.group_menu = ctk.CTkOptionMenu(frm, values=[""], variable=self.group_var)
        self.group_menu.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="X").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.entry_x = ctk.CTkEntry(frm, width=90)
        self.entry_x.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="Y").grid(row=3, column=0, sticky="w")
        self.entry_y = ctk.CTkEntry(frm, width=90)
        self.entry_y.grid(row=3, column=1, sticky="w", padx=(8, 0))

        ctk.CTkLabel(frm, text="Largeur (groupe)").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        self.entry_w = ctk.CTkEntry(frm, width=90)
        self.entry_w.grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ctk.CTkLabel(frm, text="Hauteur (groupe)").grid(row=5, column=0, sticky="w")
        self.entry_h = ctk.CTkEntry(frm, width=90)
        self.entry_h.grid(row=5, column=1, sticky="w", padx=(8, 0))

        # Appliquer
        btns = ctk.CTkFrame(side)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_apply = ctk.CTkButton(
            btns, text="Appliquer", command=self._apply_changes, state="disabled"
        )
        self.btn_apply.pack(side="left", padx=6)

        # Entrée ↵ applique
        for e in (
            self.entry_name,
            self.entry_x,
            self.entry_y,
            self.entry_w,
            self.entry_h,
        ):
            e.bind("<Return>", lambda _e: self._apply_changes())

        # Status
        self.status = ctk.CTkLabel(self.root, text="Prêt", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=8, pady=6)

    def _bind_canvas_events(self):
        # Drag des zones (gauche)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        # Pan (main) : clic milieu OU clic droit
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

    # ---------- Jeux / fichiers ----------
    def _refresh_games_list(self):
        base = self.base_dir
        games = ZoneProject.list_games(base)
        if not games:
            self.game_menu.configure(values=[""])
            self.game_var.set("")
            return

        self.game_menu.configure(values=games)
        game_name = DEFAULT_GAME_NAME if DEFAULT_GAME_NAME in games else games[0]
        self.game_var.set(game_name)
        self._on_select_game(game_name)

    def _on_select_game(self, game_name: str):
        if not game_name:
            return

        base = self.base_dir

        # Charge la config du jeu (regions, templates, etc.)
        self.project.load_game(base, game_name)

        if not self.project.image_path:
            raise FileNotFoundError(f"Image introuvable pour {game_name}")

        img = Image.open(self.project.image_path).convert("RGB")
        self.project.image = img

        # Alignement + rendu
        self._startup_align_groups()
        self._prepare_display_image()
        self._reset_canvas()
        self._redraw_all()
        self._populate_regions_list()
        self._populate_group_menu()

        self.btn_save.configure(state="normal")
        self.btn_apply.configure(state="normal")
        self.status.configure(text=f"{game_name}: {len(self.project.regions)} région(s)")

        # Auto-sélectionne la 1ère région
        keys = sorted(self.project.regions.keys())
        if keys:
            first = keys[0]
            self._last_key = first
            self._select_key_in_list(first)
            self._on_select_region_from_list()

    def _startup_align_groups(self):
        groups: dict[str, List[str]] = {}
        for k, r in self.project.regions.items():
            g = r.get("group", "")
            groups.setdefault(g, []).append(k)

        for g, keys in groups.items():
            if not self.project.group_has_lock_same_y(g):
                continue
            if not keys:
                continue
            keys_sorted = sorted(keys)
            anchor_key = keys_sorted[0]
            x, y = self.project.regions[anchor_key]["top_left"]
            self.project.set_region_pos(anchor_key, x, y)

    # ---------- Image / zoom ----------
    def _prepare_display_image(self):
        W, H = self.project.image_size
        if W == 0 or H == 0:
            return
        # 100% = 1:1
        self.base_scale = 1.0
        self._update_display_image()

    def _update_display_image(self):
        img = self.project.image
        if img is None:
            return
        # scale = zoom utilisateur, base_scale toujours 1.0
        self.scale = max(0.05, max(0.1, float(self.user_zoom)))
        disp = img.resize(
            (int(img.width * self.scale), int(img.height * self.scale)), Image.LANCZOS
        )
        self.tk_img = ImageTk.PhotoImage(disp)
        pct = int(round(self.scale * 100))
        self.zoom_pct_label.configure(text=f"{pct}%")
        self._reset_canvas()

    def _reset_canvas(self):
        self.canvas.delete("all")
        self.rect_items.clear()
        self.text_items.clear()

        if self.tk_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            # Surface virtuelle = taille de l'image → pan possible
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

    # ---------- Dessin ----------
    def _overlay_stroke_width(self) -> int:
        """Keep detection rectangles readable when the image is displayed smaller."""
        scale = self.scale if self.scale > 0 else 1.0
        return max(2, min(7, int(round(2.0 / scale))))

    def _redraw_all(self):
        self.canvas.delete("all")
        self.rect_items.clear()
        self.text_items.clear()

        if self.tk_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

        W, H = self.project.image_size
        if W == 0:
            return

        s = self.scale
        stroke_width = self._overlay_stroke_width()
        for key, r in self.project.regions.items():
            group = r.get("group", "")
            w, h = self.project.get_group_size(group)
            x, y = r["top_left"]
            dx0, dy0 = int(x * s), int(y * s)
            dx1, dy1 = int((x + w) * s), int((y + h) * s)
            rid = self.canvas.create_rectangle(
                dx0, dy0, dx1, dy1, outline="#0ea5e9", width=stroke_width
            )
            tid = self.canvas.create_text(
                dx0 + 6,
                dy0 + 6,
                anchor="nw",
                text=str(r.get("label", key)),
                fill="#0ea5e9",
                font=("Segoe UI", 10, "bold"),
            )
            self.rect_items[key] = rid
            self.text_items[key] = tid

    # ---------- Liste & champs ----------
    def _populate_regions_list(self):
        self.listbox.delete(0, tk.END)
        for k in sorted(self.project.regions.keys()):
            lab = self.project.regions[k].get("label", k)
            self.listbox.insert(tk.END, f"{k}  —  {lab}")

    def _populate_group_menu(self):
        groups = sorted(list(self.project.templates_resolved.keys())) or [""]
        self.group_menu.configure(values=groups)
        if groups:
            self.group_var.set(groups[0])

    def _current_selection_key(self) -> Optional[str]:
        sel = self.listbox.curselection()
        if not sel:
            return None
        line = self.listbox.get(sel[0])
        return line.split("  —  ", 1)[0]

    def _select_key_in_list(self, key: str):
        keys = sorted(self.project.regions.keys())
        if key in keys:
            idx = keys.index(key)
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(idx)
            self.listbox.activate(idx)

    def _on_select_region_from_list(self, event=None):
        key = self._current_selection_key()
        if not key:
            return

        r = self.project.regions[key]

        self.entry_name.delete(0, tk.END)
        self.entry_name.insert(0, key)

        group = r.get("group", "")
        if group and group not in self.project.templates:
            self.project.templates[group] = {"size": [60, 40], "type": "mix"}

        # MAJ menu des groupes
        groups = sorted(list(self.project.templates_resolved.keys())) or [""]
        self.group_menu.configure(values=groups)
        if group in groups:
            self.group_var.set(group)
        elif groups:
            self.group_var.set(groups[0])

        x, y = r["top_left"]
        self.entry_x.delete(0, tk.END)
        self.entry_x.insert(0, str(int(x)))
        self.entry_y.delete(0, tk.END)
        self.entry_y.insert(0, str(int(y)))

        gw, gh = self.project.get_group_size(r.get("group", ""))
        self.entry_w.delete(0, tk.END)
        self.entry_w.insert(0, str(int(gw)))
        self.entry_h.delete(0, tk.END)
        self.entry_h.insert(0, str(int(gh)))

        self.btn_apply.configure(state="normal")
        self._last_key = key

    # ---------- Drag & drop zones (gauche) ----------
    def _region_at_point(self, x: int, y: int) -> Optional[str]:
        for key, r in self.project.regions.items():
            gw, gh = self.project.get_group_size(r.get("group", ""))
            px, py = r["top_left"]
            if px <= x <= px + gw and py <= y <= py + gh:
                return key
        return None

    def _on_mouse_down(self, event):
        s = self.scale if self.scale else 1.0
        # coord dans le repère image (pas canvas)
        x, y = int(self.canvas.canvasx(event.x) / s), int(self.canvas.canvasy(event.y) / s)
        key = self._region_at_point(x, y)
        if key:
            self.dragging_key = key
            tlx, tly = self.project.regions[key]["top_left"]
            self.drag_offset = (x - tlx, y - tly)
            self._select_key_in_list(key)
            self._on_select_region_from_list()
            self._last_key = key
        else:
            self.dragging_key = None

    def _on_mouse_drag(self, event):
        if not self.dragging_key:
            return
        key = self.dragging_key
        s = self.scale if self.scale else 1.0
        x = int(self.canvas.canvasx(event.x) / s) - self.drag_offset[0]
        y = int(self.canvas.canvasy(event.y) / s) - self.drag_offset[1]
        self.project.set_region_pos(key, x, y)
        self._redraw_group(self.project.regions[key]["group"])

        px, py = self.project.regions[key]["top_left"]
        self.entry_x.delete(0, tk.END)
        self.entry_x.insert(0, str(px))
        self.entry_y.delete(0, tk.END)
        self.entry_y.insert(0, str(py))

    def _on_mouse_up(self, event):
        self.dragging_key = None

    def _redraw_group(self, group: str):
        s = self.scale if self.scale else 1.0
        stroke_width = self._overlay_stroke_width()
        keys = [k for k, r in self.project.regions.items() if r.get("group") == group]
        for k in keys:
            r = self.project.regions[k]
            w, h = self.project.get_group_size(group)
            x, y = r["top_left"]
            dx0, dy0 = int(x * s), int(y * s)
            dx1, dy1 = int((x + w) * s), int((y + h) * s)
            rid = self.rect_items.get(k)
            tid = self.text_items.get(k)
            if rid:
                self.canvas.coords(rid, dx0, dy0, dx1, dy1)
                self.canvas.itemconfigure(rid, width=stroke_width)
            if tid:
                self.canvas.coords(tid, dx0 + 6, dy0 + 6)

    # ---------- Pan (main) ----------
    def _on_pan_start(self, event):
        # point de départ pour le scan
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event):
        # déplacement de la vue (viewport) sans modifier les coords des objets
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    # ---------- Actions ----------
    def _apply_changes(self):
        key = self._current_selection_key() or self._last_key
        if not key:
            return

        r = self.project.regions[key]

        # Rename
        new_key = (self.entry_name.get() or key).strip()
        if new_key and new_key != key:
            new_key = self.project.rename_region(key, new_key)
            key = new_key
            r = self.project.regions[key]
            self._last_key = key

        # Group
        group = (self.group_var.get() or r.get("group", "")).strip()
        self.project.set_region_group(key, group)

        # Position
        x = int(self.entry_x.get())
        y = int(self.entry_y.get())
        self.project.set_region_pos(key, x, y)

        # Taille (propagée au groupe)
        nw = int(self.entry_w.get())
        nh = int(self.entry_h.get())
        if nw > 0 and nh > 0:
            g = self.project.regions[key]["group"]
            self.project.set_group_size(g, nw, nh)

        self._populate_regions_list()
        g = self.project.regions[key]["group"]
        self._redraw_group(g)
        self._select_key_in_list(key)
        self._on_select_region_from_list()
        self.status.configure(text=f"Modifié: {key}")

    def _save_json(self):
        """Écrit directement config/<jeu>/coordinates.json, uniquement sur clic bouton."""
        game = self.project.current_game or DEFAULT_GAME_NAME
        out_path = os.path.join(self.base_dir, game, "coordinates.json")
        self.project.save_to(out_path)
        self.status.configure(text=f"Sauvegardé: {out_path}")

    # ---------- Fermeture ----------
    def _on_close(self):
        """Fermeture sans aucune sauvegarde implicite."""
        self.root.destroy()

    # ---------- Zoom ----------
    def _on_zoom_slider(self, value: float):
        self.user_zoom = float(value)
        self._update_display_image()
        self._redraw_all()

    def _zoom_85(self):
        """Remet le zoom à 85 % via le bouton 'Ajuster'."""
        self.user_zoom = 0.85
        self.zoom_slider.set(self.user_zoom)
        self._update_display_image()
        self._redraw_all()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ZoneEditorCTK()
    app.run()
