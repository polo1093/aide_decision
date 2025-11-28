"""
"""
Exportable zone editor that runs without project dependencies.
- Captures the current screen immediately when launched (no file lookup).
- Lets you drag and edit rectangles on top of the captured screenshot.
- Keeps rectangles of the same type (e.g. "Player") at a shared size.
- Saves regions to a standalone JSON file (`coordonates.json`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

APP_TITLE = "Zone Editor (Exportable)"
DEFAULT_JSON_PATH = Path(__file__).resolve().parent / "coordonates.json"

COMMENT = (
    "Fichier exporté : lancez le script, placez les rectangles sur la capture d'écran, "
    "puis cliquez sur Enregistrer pour mettre à jour coordonates.json."
)


class SimpleProject:
    def __init__(self, json_path: Path = DEFAULT_JSON_PATH):
        self.json_path = json_path
        self.image: Image.Image = ImageGrab.grab().convert("RGB")
        self.image_path = "capture_ecran_en_cours"
        self.templates: Dict[str, Dict[str, object]] = {
            "Player": {"size": [140, 90], "type": "fixed"},
            "Currency": {"size": [120, 70], "type": "fixed"},
            "OCR": {"size": [200, 80], "type": "ocr"},
            "Example": {"size": [160, 100], "type": "mix"},
        }
        self.regions: Dict[str, Dict[str, object]] = {}
        self.comment: str = COMMENT

        if self.json_path.exists():
            self._load_from_json()
        else:
            self._load_defaults()

    @property
    def image_size(self) -> Tuple[int, int]:
        return (self.image.width, self.image.height)

    def _load_defaults(self):
        self.regions = {
            "currency_1": {
                "top_left": [80, 120],
                "group": "Currency",
                "label": "Currency 1",
            },
            "currency_2": {
                "top_left": [80, 220],
                "group": "Currency",
                "label": "Currency 2",
            },
            "value_currency_1_ocr": {
                "top_left": [320, 120],
                "group": "OCR",
                "label": "Value currency 1 OCR",
            },
            "zone_ocr": {
                "top_left": [320, 220],
                "group": "OCR",
                "label": "Zone OCR",
            },
            "example_rectangle": {
                "top_left": [560, 160],
                "group": "Example",
                "label": "Example rectangle",
            },
        }

    def _load_from_json(self):
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        self.comment = data.get("comment", COMMENT)
        self.templates.update(data.get("templates", {}))
        self.regions = data.get("regions", {})

    def save_to(self, path: Path | str):
        payload = {
            "comment": self.comment,
            "templates": self.templates,
            "regions": self.regions,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_group_size(self, group: str) -> Tuple[int, int]:
        t = self.templates.get(group, {"size": [80, 60]})
        w, h = t.get("size", [80, 60])
        return int(w), int(h)

    def set_group_size(self, group: str, w: int, h: int):
        if group not in self.templates:
            self.templates[group] = {"size": [w, h], "type": "fixed"}
        else:
            self.templates[group]["size"] = [w, h]

    def set_region_pos(self, key: str, x: int, y: int):
        self.regions[key]["top_left"] = [int(x), int(y)]

    def set_region_group(self, key: str, group: str):
        self.regions[key]["group"] = group
        if group not in self.templates:
            self.templates[group] = {"size": [80, 60], "type": "fixed"}

    def rename_region(self, old: str, new: str) -> str:
        if old == new:
            return old
        if new in self.regions:
            suffix = 2
            base = new
            while f"{base}_{suffix}" in self.regions:
                suffix += 1
            new = f"{base}_{suffix}"
        self.regions[new] = self.regions.pop(old)
        return new


class ZoneEditorCTK:
    def __init__(self, json_path: Optional[str] = None):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(APP_TITLE)
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.project = SimpleProject(Path(json_path) if json_path else DEFAULT_JSON_PATH)

        self.tk_img: Optional[ImageTk.PhotoImage] = None
        self.base_scale: float = 1.0
        self.user_zoom: float = 0.85
        self.scale: float = 1.0

        self.rect_items: Dict[str, int] = {}
        self.text_items: Dict[str, int] = {}
        self.dragging_key: Optional[str] = None
        self.drag_offset: Tuple[int, int] = (0, 0)
        self._last_key: Optional[str] = None

        self._build_ui()
        self._bind_canvas_events()
        self._prepare_display_image()
        self._reset_canvas()
        self._redraw_all()
        self._populate_regions_list()
        self._populate_group_menu()

    def _build_ui(self):
        top = ctk.CTkFrame(self.root, corner_radius=0)
        top.pack(side="top", fill="x")

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

        self.btn_adjust = ctk.CTkButton(
            top, text="Ajuster", width=80, command=self._zoom_85
        )
        self.btn_adjust.pack(side="left", padx=4, pady=8)

        self.btn_save = ctk.CTkButton(
            top, text="Enregistrer", command=self._save_json, state="normal"
        )
        self.btn_save.pack(side="left", padx=8, pady=8)

        main = ctk.CTkFrame(self.root)
        main.pack(side="top", fill="both", expand=True)

        cf = ctk.CTkFrame(main)
        cf.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)
        self.canvas = tk.Canvas(
            cf,
            bg="#F2F2F2",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

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

        ctk.CTkLabel(frm, text="Type").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.group_var = tk.StringVar(value="")
        self.group_menu = ctk.CTkOptionMenu(frm, values=[""], variable=self.group_var)
        self.group_menu.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="X").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.entry_x = ctk.CTkEntry(frm, width=90)
        self.entry_x.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ctk.CTkLabel(frm, text="Y").grid(row=3, column=0, sticky="w")
        self.entry_y = ctk.CTkEntry(frm, width=90)
        self.entry_y.grid(row=3, column=1, sticky="w", padx=(8, 0))

        ctk.CTkLabel(frm, text="Largeur (type)").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        self.entry_w = ctk.CTkEntry(frm, width=90)
        self.entry_w.grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ctk.CTkLabel(frm, text="Hauteur (type)").grid(row=5, column=0, sticky="w")
        self.entry_h = ctk.CTkEntry(frm, width=90)
        self.entry_h.grid(row=5, column=1, sticky="w", padx=(8, 0))

        btns = ctk.CTkFrame(side)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_apply = ctk.CTkButton(
            btns, text="Appliquer", command=self._apply_changes, state="normal"
        )
        self.btn_apply.pack(side="left", padx=6)

        for e in (
            self.entry_name,
            self.entry_x,
            self.entry_y,
            self.entry_w,
            self.entry_h,
        ):
            e.bind("<Return>", lambda _e: self._apply_changes())

        self.status = ctk.CTkLabel(self.root, text="Prêt", anchor="w")
        self.status.pack(side="bottom", fill="x", padx=8, pady=6)

    def _bind_canvas_events(self):
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

    def _prepare_display_image(self):
        W, H = self.project.image_size
        if W == 0 or H == 0:
            return
        self.base_scale = 1.0
        self._update_display_image()

    def _update_display_image(self):
        img = self.project.image
        if img is None:
            return
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
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

    def _redraw_all(self):
        self.canvas.delete("all")
        self.rect_items.clear()
        self.text_items.clear()

        if self.tk_img:
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
            self.canvas.config(
                scrollregion=(0, 0, self.tk_img.width(), self.tk_img.height())
            )

        W, _H = self.project.image_size
        if W == 0:
            return

        s = self.scale
        for key, r in self.project.regions.items():
            group = r.get("group", "")
            w, h = self.project.get_group_size(group)
            x, y = r["top_left"]
            dx0, dy0 = int(x * s), int(y * s)
            dx1, dy1 = int((x + w) * s), int((y + h) * s)
            rid = self.canvas.create_rectangle(
                dx0, dy0, dx1, dy1, outline="#0ea5e9", width=2
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

    def _populate_regions_list(self):
        self.listbox.delete(0, tk.END)
        for k in sorted(self.project.regions.keys()):
            lab = self.project.regions[k].get("label", k)
            self.listbox.insert(tk.END, f"{k}  —  {lab}")

    def _populate_group_menu(self):
        groups = sorted(list(self.project.templates.keys())) or [""]
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

        groups = sorted(list(self.project.templates.keys())) or [""]
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

    def _region_at_point(self, x: int, y: int) -> Optional[str]:
        for key, r in self.project.regions.items():
            gw, gh = self.project.get_group_size(r.get("group", ""))
            px, py = r["top_left"]
            if px <= x <= px + gw and py <= y <= py + gh:
                return key
        return None

    def _on_mouse_down(self, event):
        s = self.scale if self.scale else 1.0
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
            if tid:
                self.canvas.coords(tid, dx0 + 6, dy0 + 6)

    def _on_pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _apply_changes(self):
        key = self._current_selection_key() or self._last_key
        if not key:
            return

        r = self.project.regions[key]

        new_key = (self.entry_name.get() or key).strip()
        if new_key and new_key != key:
            new_key = self.project.rename_region(key, new_key)
            key = new_key
            r = self.project.regions[key]
            self._last_key = key

        group = (self.group_var.get() or r.get("group", "")).strip()
        self.project.set_region_group(key, group)

        x = int(self.entry_x.get())
        y = int(self.entry_y.get())
        self.project.set_region_pos(key, x, y)

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
        self.project.save_to(self.project.json_path)
        self.status.configure(text=f"Sauvegardé: {self.project.json_path}")

    def _on_close(self):
        self.root.destroy()

    def _on_zoom_slider(self, value: float):
        self.user_zoom = float(value)
        self._update_display_image()
        self._redraw_all()

    def _zoom_85(self):
        self.user_zoom = 0.85
        self.zoom_slider.set(self.user_zoom)
        self._update_display_image()
        self._redraw_all()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ZoneEditorCTK()
    app.run()
