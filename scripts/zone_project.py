# zone_project.py
# Logique "métier" : modèle, opérations, lecture/écriture JSON, clamp
# Aucune dépendance UI. Dépend de pillow uniquement pour charger l'image.

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Mapping, Iterable
from collections import OrderedDict
from PIL import Image

from objet.services.game import Game
from _utils import clamp_top_left, coerce_int, resolve_templates


def _load_templated_json(coord_path: str) -> Dict[str, Any]:
    """Charge coordinates.json et valide le format minimal.

    Si le fichier est invalide, on laisse l'exception remonter.
    """
    with open(coord_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not (isinstance(data, dict) and "templates" in data and "regions" in data):
        raise ValueError(f"coordinates.json invalide: {coord_path}")
    return data


class ZoneProject:
    """
    Représente un "projet" de zones pour un jeu (image + zones + templates).

    Gère :
      - chargement/écriture JSON,
      - manipulations des régions,
      - tailles de groupe,
      - contraintes lock_same_y.
    """

    def __init__(self, game: Optional[Game] = None) -> None:
        self.game = game or Game.for_script(Path(__file__).name)
        self.base_dir: str = ""
        self.current_game: Optional[str] = None
        self.image_path: Optional[str] = None
        self.image: Optional[Image.Image] = None

        # Capture/table (copie initiale de la config du jeu)
        self.table_capture: Dict[str, Any] = self.game.table.captures.table_capture

        # Données décrites par le JSON
        self.templates: Dict[str, Any] = self.game.table.captures.templates
        self._templates_resolved: Dict[str, Any] = {}
        # regions : key -> {"group": str, "top_left":[x,y], "value": Any, "label": str}
        self.regions: "OrderedDict[str, Dict[str, Any]]" = self.game.table.captures.regions

    # ---------- Propriétés utiles ----------
    @property
    def image_size(self) -> Tuple[int, int]:
        if self.image is None:
            return 0, 0
        return self.image.width, self.image.height

    @property
    def templates_resolved(self) -> Dict[str, Any]:
        # recalcul léger à la demande
        return resolve_templates(self.templates)

    def get_group_size(self, group: str) -> Tuple[int, int]:
        size = self.templates_resolved.get(group, {}).get("size", [60, 40])
        return coerce_int(size[0], 60), coerce_int(size[1], 40)

    def group_has_lock_same_y(self, group: str) -> bool:
        layout = self.templates_resolved.get(group, {}).get("layout", {})
        return bool(layout.get("lock_same_y", False))

    # ---------- Découverte ----------
    @staticmethod
    def _find_expected_image(folder: str) -> Optional[str]:
        """Retourne une capture plausible pour *folder* (full screen/table)."""

        prefer_bases = [
            "example_full_screen",
            "test_screen",
            "test_fullscreen",
            "test_table",
            
        ]
        exts = [".png", ".jpg", ".jpeg"]

        for base in prefer_bases:
            for ext in exts:
                candidate = os.path.join(folder, base + ext)
                if os.path.isfile(candidate):
                    return candidate

        def _iter_image_files() -> Iterable[Tuple[str, str]]:
            entries = sorted(os.listdir(folder))
            for name in entries:
                lower = name.lower()
                if any(lower.endswith(ext) for ext in exts):
                    yield name, lower

        screens_dir = os.path.join(folder, "entrainement", "screens")
        if os.path.isdir(screens_dir):
            for name in sorted(os.listdir(screens_dir)):
                lower = name.lower()
                if any(lower.endswith(ext) for ext in exts):
                    return os.path.join(screens_dir, name)

        # 1er passage : évite les "anchor"/"crop" si possible
        for name, lower in _iter_image_files():
            if any(tag in lower for tag in ("anchor", "crop")):
                continue
            return os.path.join(folder, name)

        # 2e passage : prend la première image trouvée
        for name, _lower in _iter_image_files():
            return os.path.join(folder, name)

        return None

    @staticmethod
    def _default_table_capture(width: int, height: int) -> Dict[str, Any]:
        w = max(0, int(width))
        h = max(0, int(height))
        return {
            "enabled": True,
            "bounds": [0, 0, w, h],
            "origin": [0, 0],
            "size": [w, h],
        }

    @staticmethod
    def _normalise_table_capture(
        raw: Optional[Mapping[str, Any]],
        width: int,
        height: int,
    ) -> Dict[str, Any]:
        base = ZoneProject._default_table_capture(width, height)
        payload: Mapping[str, Any]
        payload = raw if isinstance(raw, Mapping) else {}

        result: Dict[str, Any] = dict(base)
        for key, value in payload.items():
            if key == "relative_bounds":
                continue
            result[key] = value

        def _as_pair(value: Any) -> Optional[Tuple[int, int]]:
            if isinstance(value, Iterable):
                values = list(value)
            else:
                return None
            if not values:
                return None
            x = coerce_int(values[0])
            y = coerce_int(values[1]) if len(values) >= 2 else 0
            return x, y

        def _as_bounds(value: Any) -> Optional[List[int]]:
            if isinstance(value, Iterable):
                values = list(value)
            else:
                return None
            if len(values) < 4:
                return None
            x1 = coerce_int(values[0])
            y1 = coerce_int(values[1])
            x2 = coerce_int(values[2])
            y2 = coerce_int(values[3])
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            return [x1, y1, x2, y2]

        bounds = _as_bounds(result.get("bounds"))
        if bounds is None and isinstance(payload, Mapping):
            rel = payload.get("relative_bounds")
            if isinstance(rel, Iterable):
                rel_vals = list(rel)
            else:
                rel_vals = []
            if len(rel_vals) >= 4:
                x = coerce_int(rel_vals[0])
                y = coerce_int(rel_vals[1])
                w = max(0, coerce_int(rel_vals[2]))
                h = max(0, coerce_int(rel_vals[3]))
                bounds = [x, y, x + w, y + h]
        if bounds is None:
            origin = _as_pair(result.get("origin"))
            size = _as_pair(result.get("size"))
            if origin and size:
                ox, oy = origin
                sw = max(0, size[0])
                sh = max(0, size[1])
                bounds = [ox, oy, ox + sw, oy + sh]
        if bounds is None:
            bounds = base["bounds"]
        result["bounds"] = bounds

        origin = _as_pair(result.get("origin"))
        if origin is None:
            origin = (bounds[0], bounds[1])
        result["origin"] = [origin[0], origin[1]]

        size = _as_pair(result.get("size"))
        if size is None:
            size = (max(0, bounds[2] - bounds[0]), max(0, bounds[3] - bounds[1]))
        result["size"] = [max(0, size[0]), max(0, size[1])]

        ref_offset = _as_pair(result.get("ref_offset"))
        if ref_offset is not None:
            result["ref_offset"] = [ref_offset[0], ref_offset[1]]
        elif "ref_offset" in result:
            del result["ref_offset"]

        result["enabled"] = bool(result.get("enabled", True))
        return result

    @staticmethod
    def list_games(base_dir: str) -> List[str]:
        """Retourne la liste des jeux (dossiers avec au moins une image)."""
        games: List[str] = []
        for name in sorted(os.listdir(base_dir)):
            full = os.path.join(base_dir, name)
            if os.path.isdir(full) and ZoneProject._find_expected_image(full):
                games.append(name)
        return games

    # ---------- Chargement ----------
    def load_game(self, base_dir: str, game_name: str) -> None:
        """Charge un jeu : image + coordinates.json.

        Ici on ne "corrige" pas les positions à l'ouverture, on reprend le JSON tel quel.
        """
        self.base_dir = os.path.abspath(base_dir)
        self.current_game = game_name

        folder = os.path.join(self.base_dir, game_name)
        img_path = ZoneProject._find_expected_image(folder)
        coord_path = os.path.join(folder, "coordinates.json")

        if not img_path or not os.path.isfile(img_path):
            raise FileNotFoundError(f"Image introuvable: {img_path or folder}")

        self.image_path = img_path
        self.image = Image.open(img_path).convert("RGBA")
        W, H = self.image_size

        # Réinit capture / templates / regions depuis le fichier
        self.table_capture = self._default_table_capture(W, H)
        self.templates = {}
        self.regions = OrderedDict()

        if os.path.isfile(coord_path):
            data = _load_templated_json(coord_path)
            self.table_capture = self._normalise_table_capture(
                data.get("table_capture"), W, H
            )
            self.templates.update(data.get("templates", {}))
            regs = data.get("regions", {})
            for key, r in regs.items():
                group = r.get("group", "")
                # *** PAS DE VALEUR PAR DÉFAUT ***
                tl = r["top_left"]
                meta = {
                    meta_key: meta_value
                    for meta_key, meta_value in r.items()
                    if meta_key not in {"group", "top_left", "value", "label"}
                }
                self.regions[key] = {
                    "group": group,
                    "top_left": [coerce_int(tl[0]), coerce_int(tl[1])],
                    "value": r.get("value"),
                    "label": r.get("label", key),
                    **meta,
                }
            # IMPORTANT : plus de _clamp_all() ici → on respecte le JSON
        else:
            # base minimale si pas de JSON
            self.templates.update(
                {"action_button": {"size": [165, 70], "type": "texte"}}
            )

        self._sync_game_capture()

    def _sync_game_capture(self) -> None:
        self.game.update_from_capture(
            table_capture=self.table_capture,
            regions=self.regions,
            templates=self.templates,
            reference_path=self.image_path,
        )

    # ---------- Opérations régions ----------
    def list_regions(self) -> List[str]:
        return list(self.regions.keys())

    def get_region(self, key: str) -> Dict[str, Any]:
        return self.regions[key]

    def rename_region(self, old_key: str, new_key: str) -> str:
        if new_key == old_key:
            return old_key
        if old_key not in self.regions:
            raise KeyError(f"Region inconnue: {old_key}")
        if new_key in self.regions:
            raise KeyError(f"Nouvelle clé déjà existante: {new_key}")
        r = self.regions.pop(old_key)
        r["label"] = new_key
        self.regions[new_key] = r
        return new_key

    def set_region_group(self, key: str, group: str) -> None:
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")
        if group not in self.templates:
            # crée un groupe par défaut si inconnu
            self.templates[group] = {"size": [60, 40], "type": "mix"}
        self.regions[key]["group"] = group
        self._clamp_region(key)

    def set_region_pos(self, key: str, x: int, y: int) -> None:
        """Déplace une région. Si lock_same_y, aligne Y de toutes les régions du groupe."""
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")

        g = self.regions[key]["group"]
        gw, gh = self.get_group_size(g)
        W, H = self.image_size

        # clamp et pose la région cible
        x, y = clamp_top_left(x, y, gw, gh, W, H)
        self.regions[key]["top_left"] = [x, y]

        # si contrainte d'alignement, propage Y
        if self.group_has_lock_same_y(g):
            self._enforce_lock_same_y(g, anchor_y=y)

    def add_region(self, group: str, name: Optional[str] = None) -> str:
        if group not in self.templates:
            self.templates[group] = {"size": [60, 40], "type": "mix"}
        W, H = self.image_size
        gw, gh = self.get_group_size(group)
        x, y = clamp_top_left(W // 2 - gw // 2, H // 2 - gh // 2, gw, gh, W, H)
        base = name or f"{group}_"
        if not name:
            i = 1
            while f"{base}{i}" in self.regions:
                i += 1
            key = f"{base}{i}"
        else:
            key = name
            if key in self.regions:
                i = 2
                while f"{key}_{i}" in self.regions:
                    i += 1
                key = f"{key}_{i}"
        self.regions[key] = {
            "group": group,
            "top_left": [x, y],
            "value": None,
            "label": key,
        }
        return key

    def delete_region(self, key: str) -> None:
        if key in self.regions:
            self.regions.pop(key)

    # ---------- Opérations groupes ----------
    def set_group_size(self, group: str, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            raise ValueError("Taille de groupe invalide")
        base = self.templates.get(group, {"type": "mix"})
        base["size"] = [int(w), int(h)]
        self.templates[group] = base
        # re-clamp toutes les régions de ce groupe
        for k, r in self.regions.items():
            if r.get("group") == group:
                self._clamp_region(k)
        # si lock_same_y → réaligner le Y commun
        if self.group_has_lock_same_y(group):
            self._enforce_lock_same_y(group, anchor_y=None)

    # ---------- Sauvegarde ----------
    def export_payload(self) -> Dict[str, Any]:
        W, H = self.image_size
        tc = self._normalise_table_capture(self.table_capture, W, H)
        out: Dict[str, Any] = {
            "table_capture": tc,
            "templates": self.templates,
            "regions": {},
        }
        for key, r in self.regions.items():
            tl = r["top_left"]  # *** pas de fallback [0,0] ***
            out["regions"][key] = {
                "group": r.get("group", ""),
                "top_left": [int(tl[0]), int(tl[1])],
                "value": r.get("value", None),
                "label": r.get("label", key),
            }
            for meta_key, meta_value in r.items():
                if meta_key not in {"group", "top_left", "value", "label"}:
                    out["regions"][key][meta_key] = meta_value
        return out

    def save_to(self, path: str) -> None:
        payload = self.export_payload()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ---------- internes ----------
    def _clamp_all(self) -> None:
        for k in list(self.regions.keys()):
            self._clamp_region(k)

    def _clamp_region(self, key: str) -> None:
        if key not in self.regions:
            raise KeyError(f"Region inconnue: {key}")
        W, H = self.image_size
        g = self.regions[key]["group"]
        gw, gh = self.get_group_size(g)
        x, y = self.regions[key]["top_left"]  # *** pas de .get(...,[0,0]) ***
        x, y = clamp_top_left(coerce_int(x), coerce_int(y), gw, gh, W, H)
        self.regions[key]["top_left"] = [x, y]

    def _enforce_lock_same_y(self, group: str, anchor_y: Optional[int]) -> None:
        """
        Aligne toutes les régions du groupe sur un même Y:
        - si anchor_y est fourni → on l'utilise (puis clamp commun).
        - sinon → min des Y existants (puis clamp commun).
        Clamp du X conservé par région.
        """
        keys = [k for k, r in self.regions.items() if r.get("group") == group]
        if not keys:
            return

        gw, gh = self.get_group_size(group)
        W, H = self.image_size

        if anchor_y is None:
            current_ys = [coerce_int(self.regions[k]["top_left"][1], 0) for k in keys]
            target_y = min(current_ys) if current_ys else 0
        else:
            target_y = coerce_int(anchor_y, 0)

        target_y = max(0, min(target_y, max(0, H - gh)))

        for k in keys:
            x, _y = self.regions[k]["top_left"]
            x, y = clamp_top_left(coerce_int(x), target_y, gw, gh, W, H)
            self.regions[k]["top_left"] = [x, y]
