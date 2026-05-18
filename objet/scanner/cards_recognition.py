"""Card template helpers shared between scanner code and CLI tools."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
from PIL import Image

from objet.utils.pyauto import locate_in_image

__all__ = [
    "CardObservation",
    "TemplateIndex",
    "is_cover_me_cards",
    "is_card_present",
    "match_best",
    "recognize_card_observation",
    "recognize_number_and_suit",
    "trim_card_patch",
]

ROOT_TEMPLATE_SET = "__root__"


@dataclass
class CardObservation:
    """Observation brute d'une carte (issue de la capture)."""

    value: Optional[str]
    suit: Optional[str]
    value_score: float
    suit_score: float
    source: str = "capture"


class TemplateIndex:
    """Charge et organise les gabarits de cartes par *type de capture*."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.numbers: Dict[str, List[np.ndarray]] = {}
        self.suits: Dict[str, List[np.ndarray]] = {}
        self.numbers_by_set: Dict[str, Dict[str, List[np.ndarray]]] = {}
        self.suits_by_set: Dict[str, Dict[str, List[np.ndarray]]] = {}
        self.default_set: str = ROOT_TEMPLATE_SET

    @staticmethod
    def _prep(gray: np.ndarray) -> np.ndarray:
        return gray

    @staticmethod
    def _imread_gray(p: Path) -> Optional[np.ndarray]:
        try:
            img = Image.open(p).convert("L")
            return np.array(img)
        except Exception:
            return None

    def _load_dir(self, base: Path) -> Dict[str, List[np.ndarray]]:
        out: Dict[str, List[np.ndarray]] = {}
        if not base.exists():
            return out
        for label_dir in sorted(base.iterdir()):
            if not label_dir.is_dir():
                continue
            label = label_dir.name
            imgs: List[np.ndarray] = []
            for f in sorted(label_dir.glob("*.png")):
                g = self._imread_gray(f)
                if g is not None:
                    imgs.append(self._prep(g))
            if imgs:
                out[label] = imgs
        return out

    def load(self) -> None:
        """Charge les gabarits disponibles et détecte les ensembles déclarés."""

        self.numbers_by_set = {}
        self.suits_by_set = {}
        default: Optional[str] = None

        # 1) compat héritage : gabarits directement dans root/numbers|suits
        legacy_numbers = self._load_dir(self.root / "numbers")
        legacy_suits = self._load_dir(self.root / "suits")
        if legacy_numbers or legacy_suits:
            self.numbers_by_set[ROOT_TEMPLATE_SET] = legacy_numbers
            self.suits_by_set[ROOT_TEMPLATE_SET] = legacy_suits
            default = ROOT_TEMPLATE_SET

        # 2) Sous-dossiers (board/, hand/, ...)
        if self.root.exists():
            for subdir in sorted(self.root.iterdir()):
                if not subdir.is_dir():
                    continue
                numbers = self._load_dir(subdir / "numbers")
                suits = self._load_dir(subdir / "suits")
                if not numbers and not suits:
                    continue
                key = subdir.name
                self.numbers_by_set[key] = numbers
                self.suits_by_set[key] = suits
                if default is None and ROOT_TEMPLATE_SET not in self.numbers_by_set:
                    default = key

        if default is None:
            # Aucun ensemble explicite → utiliser le premier trouvé ou root
            union_keys = list({*self.numbers_by_set.keys(), *self.suits_by_set.keys()})
            default = union_keys[0] if union_keys else ROOT_TEMPLATE_SET

        self.default_set = default
        self.numbers = self.numbers_by_set.get(default, {})
        self.suits = self.suits_by_set.get(default, {})

    def _normalise_set(self, template_set: Optional[str]) -> str:
        if template_set:
            return template_set
        return self.default_set

    def get_templates(
        self,
        template_set: Optional[str] = None,
        *,
        include_fallback_sets: bool = False,
    ) -> Tuple[Dict[str, List[np.ndarray]], Dict[str, List[np.ndarray]]]:
        key = self._normalise_set(template_set)
        numbers = dict(self.numbers_by_set.get(key, {}))
        suits = dict(self.suits_by_set.get(key, {}))
        if not numbers and not suits and template_set:
            # Aucun template pour cet ensemble -> fallback silencieux sur le défaut.
            key = self.default_set
            numbers = dict(self.numbers_by_set.get(key, {}))
            suits = dict(self.suits_by_set.get(key, {}))
        if include_fallback_sets and template_set:
            for fallback_key in self._fallback_set_keys(key):
                for label, imgs in self.numbers_by_set.get(fallback_key, {}).items():
                    numbers.setdefault(label, imgs)
                for label, imgs in self.suits_by_set.get(fallback_key, {}).items():
                    suits.setdefault(label, imgs)
        return numbers, suits

    def _fallback_set_keys(self, preferred_key: str) -> List[str]:
        keys = { *self.numbers_by_set.keys(), *self.suits_by_set.keys() }
        ordered: List[str] = []
        if self.default_set in keys and self.default_set != preferred_key:
            ordered.append(self.default_set)
        ordered.extend(sorted(key for key in keys if key not in {preferred_key, self.default_set}))
        return ordered

    def available_sets(self) -> List[str]:
        keys = { *self.numbers_by_set.keys(), *self.suits_by_set.keys() }
        return sorted(keys)

    def check_missing(
        self,
        expect_numbers: Optional[Iterable[str]] = None,
        expect_suits: Optional[Iterable[str]] = None,
        *,
        template_set: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        miss: Dict[str, List[str]] = {"numbers": [], "suits": []}
        numbers, suits = self.get_templates(template_set)
        if expect_numbers:
            for v in expect_numbers:
                if v not in numbers:
                    miss["numbers"].append(v)
        if expect_suits:
            for s in expect_suits:
                if s not in suits:
                    miss["suits"].append(s)
        return miss

    def missing_cards(
        self,
        expect_numbers: Iterable[str],
        expect_suits: Iterable[str],
        *,
        template_set: Optional[str] = None,
    ) -> List[str]:
        """Liste les combinaisons valeur/couleur impossibles faute de gabarits.

        Chaque carte attendue est décrite sous la forme ``<value>_of_<suit>`` et
        annotée avec la ou les références manquantes (valeur ou couleur).
        """

        numbers, suits = self.get_templates(template_set)
        numbers_available = set(numbers)
        suits_available = set(suits)
        missing: List[str] = []
        for value in expect_numbers:
            value_ok = value in numbers_available
            for suit in expect_suits:
                suit_ok = suit in suits_available
                if value_ok and suit_ok:
                    continue
                reasons: List[str] = []
                if not value_ok:
                    reasons.append(f"number '{value}'")
                if not suit_ok:
                    reasons.append(f"suit '{suit}'")
                reason_str = " and ".join(reasons)
                missing.append(f"{value}_of_{suit} (missing {reason_str})")
        return missing

    def append_template(
        self,
        template_set: Optional[str],
        label: str,
        img: Image.Image,
        *,
        is_number: bool,
    ) -> None:
        key = self._normalise_set(template_set)
        gray = np.array(img.convert("L"))
        arr = self._prep(gray)
        store_all = self.numbers_by_set if is_number else self.suits_by_set
        store = store_all.setdefault(key, {})
        store.setdefault(label, []).append(arr)
        if key == self.default_set:
            if is_number:
                self.numbers = store
            else:
                self.suits = store
        else:
            current_keys = { *self.numbers_by_set.keys(), *self.suits_by_set.keys() }
            if self.default_set not in current_keys:
                self.default_set = key
                self.numbers = self.numbers_by_set.get(self.default_set, {})
                self.suits = self.suits_by_set.get(self.default_set, {})


def _to_gray(img):
    """Normalise un patch en niveau de gris (ndarray 2D).

    Accepte :
    - un numpy.ndarray (BGR ou déjà en gris),
    - une image PIL,
    - au pire, tout objet convertible en ndarray.
    """
    # 1) Cas OpenCV / numpy
    if isinstance(img, np.ndarray):
        # Déjà en niveaux de gris
        if img.ndim == 2:
            return img
        # Image couleur (en pratique BGR si ça vient de cv2 / screen_crop)
        if img.ndim == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        raise ValueError(f"Format ndarray inattendu pour _to_gray: shape={img.shape}")

    # 2) Cas PIL.Image
    if isinstance(img, Image.Image):
        arr = np.array(img.convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # 3) Fallback : on tente de convertir en ndarray
    arr = np.array(img)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        # On part du principe que c’est du BGR (cas le plus probable avec OpenCV)
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

    raise ValueError(f"Type d'image non supporté pour _to_gray: {type(img)}")


def trim_card_patch(img: Image.Image | np.ndarray, border: int) -> Image.Image:
    """Retourne une version rognée du patch (toujours en PIL.Image)."""

    if border <= 0:
        if isinstance(img, Image.Image):
            return img
        if isinstance(img, np.ndarray):
            if img.ndim == 2:
                return Image.fromarray(img)
            return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        return Image.fromarray(np.array(img))

    if isinstance(img, Image.Image):
        w, h = img.size
        if w <= border * 2 or h <= border * 2:
            return img
        return img.crop((border, border, w - border, h - border))

    arr = np.array(img)
    if arr.ndim not in (2, 3):
        return Image.fromarray(arr)

    h, w = arr.shape[:2]
    if w <= border * 2 or h <= border * 2:
        if arr.ndim == 2:
            return Image.fromarray(arr)
        return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))

    trimmed = arr[border : h - border, border : w - border]
    if arr.ndim == 2:
        return Image.fromarray(trimmed)
    return Image.fromarray(cv2.cvtColor(trimmed, cv2.COLOR_BGR2RGB))


def is_card_present(patch: np.ndarray | Image.Image, *, threshold: int = 240, min_ratio: float = 0.08) -> bool:
    """Heuristique simple : proportion de pixels *très clairs* sur la zone."""

    if isinstance(patch, np.ndarray):
        arr = patch
        if arr.ndim == 2:
            arr_u8 = arr.astype(np.uint8, copy=False)
            white = arr_u8 >= threshold
            ratio = float(white.mean())
            return ratio >= float(min_ratio)
        if arr.ndim == 3:
            arr_u8 = arr.astype(np.uint8, copy=False)
        else:
            raise ValueError(f"Unsupported array shape for card presence: {arr.shape}")
    elif isinstance(patch, Image.Image):
        arr_u8 = np.array(patch.convert("RGB"), dtype=np.uint8)
    else:
        raise TypeError(f"Unsupported patch type for card presence: {type(patch)!r}")

    if arr_u8.ndim == 2:
        white = arr_u8 >= threshold
    else:
        white = np.all(arr_u8 >= threshold, axis=2)

    ratio = float(white.mean())
    return ratio >= float(min_ratio)


def match_best(gray_img: np.ndarray, templates: List[np.ndarray], method: int = cv2.TM_CCOEFF_NORMED) -> float:
    best = -1.0
    for tpl in templates:
        if gray_img.shape[0] < tpl.shape[0] or gray_img.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(gray_img, tpl, method)
        _, score, _, _ = cv2.minMaxLoc(res)
        best = max(best, float(score))
    return best


def recognize_number_and_suit(
    number_patch: Image.Image,
    suit_patch: Image.Image,
    idx: TemplateIndex,
    *,
    template_set: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], float, float]:
    """Retourne (value, suit, score_value, score_suit)."""

    g_num = _to_gray(number_patch)
    g_suit = _to_gray(suit_patch)

    numbers, suits = idx.get_templates(template_set, include_fallback_sets=True)

    best_num, best_num_score = None, -1.0
    for label, tpls in numbers.items():
        score = match_best(g_num, tpls)
        if score > best_num_score:
            best_num_score = score
            best_num = label

    best_suit, best_suit_score = None, -1.0
    for label, tpls in suits.items():
        score = match_best(g_suit, tpls)
        if score > best_suit_score:
            best_suit_score = score
            best_suit = label

    return best_num, best_suit, best_num_score, best_suit_score


def recognize_card_observation(
    number_patch: Image.Image | np.ndarray,
    suit_patch: Image.Image | np.ndarray,
    idx: TemplateIndex,
    *,
    template_set: Optional[str] = None,
    trim: int = 0,
) -> CardObservation:
    """Réalise une reconnaissance complète et retourne une observation structurée."""

    trimmed_num = trim_card_patch(number_patch, trim)
    trimmed_suit = trim_card_patch(suit_patch, trim)
    value, suit, value_score, suit_score = recognize_number_and_suit(
        trimmed_num,
        trimmed_suit,
        idx,
        template_set=template_set,
    )
    return CardObservation(value, suit, float(value_score), float(suit_score))





def _ensure_pil_image(region):
    """Accepte PIL.Image ou np.ndarray et renvoie toujours une PIL.Image."""
    if isinstance(region, Image.Image):
        return region

    if isinstance(region, np.ndarray):
        arr = region
        if arr.ndim == 2:
            # image grayscale
            return Image.fromarray(arr.astype("uint8"), mode="L")
        if arr.ndim == 3:
            # typiquement BGR venant de cv2 → on repasse en RGB
            if arr.shape[2] >= 3:
                rgb = arr[..., ::-1]  # BGR -> RGB
                return Image.fromarray(rgb.astype("uint8"), mode="RGB")
        raise ValueError(f"Unsupported numpy array shape for image: {arr.shape!r}")

    raise TypeError(f"Unsupported region type: {type(region)!r}")



import pyscreeze

ACTIONS_DIR = Path(__file__).resolve().parents[2] / "config" / "PMU"

ACTION_TEMPLATES: Dict[str, Path] = {
    
    "CHECK": ACTIONS_DIR / "check.png",
    "paid": ACTIONS_DIR / "paie.png",
    "RELANCER": ACTIONS_DIR / "relance.png",
    "fold": ACTIONS_DIR / "fold.png",
    "No_start": ACTIONS_DIR / "sit_out.png",
    "play": ACTIONS_DIR / "play.png",
    
}


def action_templates_for_dir(game_dir: Path | str) -> Dict[str, Path]:
    """Build action template paths for a game configuration directory."""

    base = Path(game_dir)
    return {
        "CHECK": base / "check.png",
        "paid": base / "paie.png",
        "RELANCER": base / "relance.png",
        "fold": base / "fold.png",
        "No_start": base / "sit_out.png",
        "play": base / "play.png",
    }
 


@lru_cache(maxsize=len(ACTION_TEMPLATES)+1)
def _load_is_cover_me_cards_template(path) -> Optional[Image.Image]:
    """Load the reference template used to detect the FOLD overlay."""
    with Image.open(path) as img:
        return img.convert("RGB")


def is_cover_me_cards(
    region: Image.Image,
    threshold: float = 0.55,
    *,
    action_templates: Optional[Mapping[str, Path]] = None,
) -> bool:
    """Return ``True`` when the *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    region = _ensure_pil_image(region)
    haystack_rgb = region.convert("RGB")
    haystack_gray = cv2.cvtColor(np.array(haystack_rgb), cv2.COLOR_RGB2GRAY)
    templates = dict(action_templates or ACTION_TEMPLATES)
    templates.pop("paid", None)
    for path in templates.values():
        if is_cover(haystack_gray, path, threshold):
            return True
    return False

def is_etat_player(
    region: Image.Image,
    threshold: float = 0.55,
    *,
    action_templates: Optional[Mapping[str, Path]] = None,
) -> bool:
    """Return  *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    region = _ensure_pil_image(region)
    haystack_rgb = region.convert("RGB")
    haystack_gray = cv2.cvtColor(np.array(haystack_rgb), cv2.COLOR_RGB2GRAY)
    templates = action_templates or ACTION_TEMPLATES
    for action_name, path in templates.items():
        if is_cover(haystack_gray, path, threshold):
            return action_name
    return False
    
    
def is_cover(screen_array: np.ndarray, template_path: Path, threshold: float = 0.55,) -> bool:
    """Return ``True`` when the *fold* overlay is detected inside ``patch``."""
    # haystack = région où on cherche (player_state_me), en niveaux de gris
    if screen_array.ndim == 2:
        haystack_gray = screen_array
    else:
        haystack_rgb = cv2.cvtColor(screen_array, cv2.COLOR_BGR2RGB)
        haystack_gray = cv2.cvtColor(haystack_rgb, cv2.COLOR_RGB2GRAY)

    template_rgb = _load_is_cover_me_cards_template(template_path)
    template_gray = cv2.cvtColor(np.array(template_rgb), cv2.COLOR_RGB2GRAY)

    # matchTemplate → carte de scores normalisés
    res = cv2.matchTemplate(haystack_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)

    # max_val est la "confidence" [0, 1]
    if max_val >= threshold:
        return True
    return False
