
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import ImageGrab, Image

from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    
import pyautogui
from objet.utils.pyauto import locate_in_image
from objet.utils.calibration import bbox_from_region, load_coordinates
from objet.utils.logging_config import get_logger
from objet.scanner.cards_recognition import (
    TemplateIndex,
    action_templates_for_dir,
    is_cover_me_cards, is_etat_player,
    is_card_present,
    recognize_number_and_suit,is_cover
)
from objet.scanner.amount_ocr import OcrEngine

DEFAULT_COORD_PATH = Path("config/PMU/coordinates.json")
DEFAULT_ANCHOR_PATH = Path("config/PMU/anchor.png")
DEFAULT_CARDS_ROOT = Path("config/PMU/Cards")
DEFAULT_LOSE_PATH = Path("config/PMU/lose.png")


LOGGER = get_logger(__name__)


class ScanTable:
    """Scan de la table PMU basé sur capture écran + pyautogui.

    - Localisation de la fenêtre via un template d'ancre (me.png) avec locate_in_image().
    - ``screen_array`` conserve la capture plein écran en BGR (convention OpenCV).
    """
    #Todo fqire des objets scqn cqrds ... pour videe le fichier cards _recognition car bcp trop gros
    def __init__(
        self,
        *,
        coord_path: Path | str = DEFAULT_COORD_PATH,
        value_threshold: float = 0.75,
        suit_threshold: float = 0.75,
    ) -> None:
        # --- Config / calibration ---
        self.coord_path = Path(coord_path)
        self.game_dir = self.coord_path.parent

        # Gabarit de référence (ancre) utilisé par pyautogui/locate
        self.anchor_path = self.game_dir / "anchor.png"
        self.reference_pil: Image.Image = Image.open(self.anchor_path).convert("RGB")
        self.lose_path = self.game_dir / "lose.png"
        self.action_templates = action_templates_for_dir(self.game_dir)

        # --- État runtime ---
        self.value_threshold = value_threshold
        self.suit_threshold = suit_threshold
        self.screen_array: Optional[np.ndarray] = None     # plein écran, BGR
        self.anchor_box: Optional[Tuple[int, int, int, int]] = None
        self.scan_string: str = "init"
        self.cards_root = self.game_dir / "Cards"
        self.template_index = TemplateIndex(self.cards_root)
        self.template_index.load()
        
        regions, _, _ = load_coordinates(self.coord_path)
        self.player_state_boxes = bbox_from_region(regions.get("player_state_me"))
        self.ocr =  OcrEngine()

        # Première capture
        self.screen_refresh()
        

        

    
    def test_scan(self) -> bool:
        self.screen_refresh()
        if self.is_lose():
            LOGGER.error("ARRET - ecran_perdu detecte=True")
            sys.exit("You lose")
        found = self.find_table()
        LOGGER.debug("SCAN test_table status=%s", found)
        return found
    
    def screen_refresh(self) -> None:
        """Capture plein écran dans self.screen_array (numpy BGR)."""
        grab = ImageGrab.grab()               # PIL RGB
        rgb = np.array(grab)                  # numpy RGB
        self.screen_array = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)  # numpy BGR
        self.anchor_box = None

    # ------------------------------------------------------------------
    # Localisation de la table via pyautogui
    # ------------------------------------------------------------------
    def find_table(self, *, grayscale: bool = True, confidence: float = 0.9) -> bool:
        """Localise la table via l'ancre.

        Met à jour :
          - ``self.anchor_box`` avec la bounding box de l'ancre (left, top, w, h)
          - ``self.scan_string`` : 'ok' ou "don't find".
        """
        if self.screen_array is None:
            self.scan_string = "no_screen"
            self.anchor_box = None
            LOGGER.warning("SKIP recherche_table raison=no_screen")
            return False

        # 1) Localiser l'ancre dans le plein écran via pyautogui
        try:
            box = locate_in_image(
                haystack=self.screen_array,
                needle=self.reference_pil,
                assume_bgr=True,
                grayscale=grayscale,
                confidence=confidence,
            )
        except pyautogui.ImageNotFoundException:
            self.scan_string = "don't find"
            self.anchor_box = None
            LOGGER.warning("SKIP recherche_table raison=anchor_introuvable confidence=%s", confidence)
            return False

        anchor_left, anchor_top, anchor_w, anchor_h = box
        self.anchor_box = (int(anchor_left), int(anchor_top), int(anchor_w), int(anchor_h))
        self.scan_string = "ok"
        LOGGER.debug("SCAN table anchor=%s", self.anchor_box)
        return True

    # ------------------------------------------------------------------
    # Scan des cartes directement sur la capture plein écran
    # ------------------------------------------------------------------

    def scan_carte(
        self,
        position_value: Tuple[int, int, int, int],
        position_suit: Tuple[int, int, int, int],
        *,
        template_set: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], float, float]:
        """
        Retourne:
            (value, suit, confidence_value, confidence_suit)

        - value, suit : str ou None
        - confidence_* : float entre 0.0 et 1.0
        """
        # crops séparés pour la valeur et le symbole
        image_card_value = self._extract_patch(position_value)
        image_card_suit = self._extract_patch(position_suit)


        if template_set == "hand" and self._should_skip_for_fold(image_card_value):
            LOGGER.debug("SCAN carte skip raison=cover_main template_set=%s", template_set)
            return None, None, 0.0, 0.0

        if is_card_present(image_card_value):
            carte_value, carte_suit, score_value, score_suit = recognize_number_and_suit(
                image_card_value,
                image_card_suit,
                self.template_index,
                template_set=template_set,
            )

            conf_val = float(max(0.0, score_value or 0.0))
            conf_suit = float(max(0.0, score_suit or 0.0))

            value_ok = carte_value if (carte_value and conf_val >= self.value_threshold) else None
            suit_ok = carte_suit if (carte_suit and conf_suit >= self.suit_threshold) else None

            LOGGER.debug(
                "SCAN carte brut template_set=%s value=%s suit=%s score_value=%.3f score_suit=%.3f accepted_value=%s accepted_suit=%s",
                template_set,
                carte_value,
                carte_suit,
                conf_val,
                conf_suit,
                value_ok,
                suit_ok,
            )

            return value_ok, suit_ok, conf_val, conf_suit
        LOGGER.debug("SCAN carte vide template_set=%s", template_set)
        return None, None, 0.0, 0.0



    def _should_skip_for_fold(self,number_patch: np.ndarray) -> bool:
        state_patch = self._extract_patch(self.player_state_boxes, pad=0)
        return is_cover_me_cards(
            state_patch,
            threshold=0.6,
            action_templates=self.action_templates,
        )
        
       


    def scan_player(self, position_money,position_etat):
        etat = is_etat_player(
            self._extract_patch(position_etat),
            action_templates=self.action_templates,
        )
        value = self.scan_money( position_money)       
        return etat, value

    def scan_player_name(self, position_name) -> Optional[str]:
        if position_name is None:
            return None

        img = self._extract_patch(position_name)
        texte, confidence = self.ocr.read_text(img, normalize_whitespace=False)
        name = _clean_player_name(texte)
        LOGGER.debug("SCAN ocr_player_name raw=%r confidence=%.3f name=%s", texte, confidence, name)
        return name

    def scan_money(self, position) -> Optional[float]:
        img = self._extract_patch(position)
        value, confidence, raw_text = self.ocr.read_amount(img)
        LOGGER.debug(
            "SCAN ocr_amount raw=%r confidence=%.3f value=%s",
            raw_text,
            confidence,
            value,
        )
        return None if value is None else value


    def scan_bouton(self, position):
        img = self._extract_patch(position)
        texte, confidence = self.ocr.read_text(img)
        LOGGER.debug("SCAN ocr_button raw=%r confidence=%.3f", texte, confidence)
        return texte if texte else None


    def is_lose(self) -> bool:
        return self.lose_path.exists() and is_cover(self.screen_array, self.lose_path)
        
        
        
        
    def _extract_patch(self, box: Tuple[int, int, int, int], pad: int = 3) -> np.ndarray:
        """Retourne un crop (numpy BGR) pour ``box=(x,y,w,h)`` avec padding et clamp."""

        if self.screen_array is None:
            return np.empty((0, 0), dtype=np.uint8)

        x, y, w, h = box
        x = int(round(x))
        y = int(round(y))
        w = max(0, int(round(w)))
        h = max(0, int(round(h)))

        if w == 0 or h == 0:
            return np.empty((0, 0), dtype=np.uint8)

        x0 = max(0, int(x - pad))
        y0 = max(0, int(y - pad))

        h_scr, w_scr = self.screen_array.shape[:2]
        x1 = min(w_scr, int(x + w + pad))
        y1 = min(h_scr, int(y + h + pad))

        if x1 <= x0 or y1 <= y0:
            return np.empty((0, 0), dtype=np.uint8)

        img = self.screen_array[y0:y1, x0:x1].copy()
        return img


def _clean_player_name(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    cleaned = " ".join(str(text).split()).strip()
    return cleaned or None

if __name__ == "__main__":
    scan = ScanTable()
    print(scan.test_scan())
    

    import cv2
    import numpy as np
    from PIL import Image

    img = scan.screen_array  # BGR

    if isinstance(img, np.ndarray):
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).show()
    elif isinstance(img, Image.Image):
        img.show()
    else:
        print("Type d'image inattendu:", type(img))
        
