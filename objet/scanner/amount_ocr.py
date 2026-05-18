"""OCR utilities for reading amounts and short button texts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Compatibilité Pillow >= 10 pour EasyOCR
# ---------------------------------------------------------------------------
# Certaines versions d'EasyOCR appellent Image.ANTIALIAS, qui n'existe plus
# dans Pillow 10+. On recrée donc cet attribut en le pointant vers LANCZOS.
if not hasattr(Image, "ANTIALIAS"):
    try:
        # Pillow 10+: filtres dans Image.Resampling
        Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
    except Exception:
        # Fallback : la plupart des versions exposent encore Image.LANCZOS
        if hasattr(Image, "LANCZOS"):
            Image.ANTIALIAS = Image.LANCZOS  # type: ignore[attr-defined]

PatchType = Union[np.ndarray, Image.Image]


def _patch_bidi_get_display() -> None:
    """Expose bidi.get_display for EasyOCR when python-bidi keeps it in bidi.algorithm."""
    try:
        import bidi
        from bidi.algorithm import get_display
    except Exception:
        return

    if not hasattr(bidi, "get_display"):
        bidi.get_display = get_display  # type: ignore[attr-defined]


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace characters into a single space."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _strip_currency_symbols(text: str) -> str:
    """Remove common currency symbols and non-breaking spaces."""
    replacements = {
        "\xa0": " ",
        "€": " ",
        "$": " ",
        "£": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _fix_currency_ocr_prefix(text: str) -> str:
    """Drop a leading OCR ``5`` when it most likely represents a currency sign."""

    # PokerTH often renders amounts like "$4 980". EasyOCR may read the dollar
    # as "5", producing "54 980". Keep this correction limited to grouped
    # thousands so regular values such as "530" are not silently rewritten.
    text = re.sub(r"(?<!\d)5\s+(?=\d{1,3}(?:\s+\d{3})+(?:[.,]\d+)?\b)", "", text)
    return re.sub(r"(?<!\d)5(?=\d{1,3}(?:\s+\d{3})+(?:[.,]\d+)?\b)", "", text)


def _extract_numeric_tokens(text: str) -> list[str]:
    """Return candidate numeric tokens from an OCR string."""
    grouped = r"[0-9]+(?:\s+[0-9]{3})+(?:[.,][0-9]+)?"
    plain = r"[0-9]+(?:[.,][0-9]+)*"
    return re.findall(f"{grouped}|{plain}", text)


@dataclass
class OcrEngine:
    """Lightweight OCR engine for amounts and short texts (buttons)."""

    lang: str = "fr"
    _reader: Optional[object] = None

    def _ensure_reader(self) -> None:
        """Lazily create the OCR backend (EasyOCR Reader or similar)."""
        if self._reader is not None:
            return

        _patch_bidi_get_display()
        import easyocr  # import différé pour ne pas charger EasyOCR inutilement

        langs = [self.lang]
        if "en" not in langs:
            langs.append("en")
        self._reader = easyocr.Reader(langs, verbose=False)

    def _to_pil(self, patch: PatchType) -> Image.Image:
        """Convert any supported input (np.ndarray BGR or PIL.Image) to a PIL RGB image."""
        if isinstance(patch, Image.Image):
            return patch.convert("RGB")

        if isinstance(patch, np.ndarray):
            if patch.ndim == 2:
                rgb = np.stack([patch] * 3, axis=-1)
            elif patch.ndim == 3 and patch.shape[2] == 3:
                # BGR -> RGB
                rgb = patch[:, :, ::-1]
            else:
                raise ValueError("Unsupported numpy patch shape")
            return Image.fromarray(rgb.astype(np.uint8), mode="RGB")

        raise TypeError("Unsupported patch type")

    def read_text(
        self,
        patch: PatchType,
        *,
        normalize_whitespace: bool = True,
    ) -> tuple[Optional[str], float]:
        """Read raw text from an image patch."""
        self._ensure_reader()
        pil_image = self._to_pil(patch)

        if pil_image.width == 0 or pil_image.height == 0:
            return None, 0.0

        np_image = np.array(pil_image)
        results = self._reader.readtext(np_image, detail=1)
        if not results:
            return None, 0.0

        texts = [text for _, text, conf in results if text]
        confidences = [float(conf) for _, text, conf in results if text]

        if not texts:
            return None, 0.0

        raw_text = " ".join(texts)
        if normalize_whitespace:
            raw_text = _normalize_whitespace(raw_text)

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        confidence = max(0.0, min(1.0, confidence))
        return raw_text, confidence

    def _parse_amount_from_text(
        self,
        text: str,
        *,
        allow_comma: bool,
        allow_dot: bool,
    ) -> Optional[float]:
        cleaned_text = _strip_currency_symbols(text)
        cleaned_text = _fix_currency_ocr_prefix(cleaned_text)
        tokens = _extract_numeric_tokens(cleaned_text)

        candidates: list[float] = []
        for token in tokens:
            sanitized = token.replace(" ", "")
            if not sanitized:
                continue

            decimal_char: Optional[str] = None
            if "." in sanitized and "," in sanitized:
                # les deux présents → on considère le dernier comme séparateur décimal
                last_dot = sanitized.rfind(".")
                last_comma = sanitized.rfind(",")
                decimal_char = "." if last_dot > last_comma else ","
                other = "," if decimal_char == "." else "."
                sanitized = sanitized.replace(other, "")
            elif "," in sanitized:
                if not allow_comma:
                    continue
                decimal_char = ","
            elif "." in sanitized:
                if not allow_dot:
                    continue
                decimal_char = "."

            digits = sanitized.replace(".", "").replace(",", "")
            if decimal_char is not None:
                if decimal_char == "," and not allow_comma:
                    continue
                if decimal_char == "." and not allow_dot:
                    continue
                digits = sanitized.replace(decimal_char, ".")

            if not digits:
                continue
            if digits.count(".") > 1:
                continue
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", digits):
                continue

            candidates.append(float(digits))

        if not candidates:
            return None
        return max(candidates)

    def read_amount(
        self,
        patch: PatchType,
        *,
        allow_comma: bool = True,
        allow_dot: bool = True,
    ) -> tuple[Optional[float], float, str]:
        """Read a numeric amount from an image patch."""
        raw_text, confidence = self.read_text(patch, normalize_whitespace=False)
        if raw_text is None:
            return None, confidence, ""

        value = self._parse_amount_from_text(
            raw_text,
            allow_comma=allow_comma,
            allow_dot=allow_dot,
        )
        return value, confidence, raw_text


_GLOBAL_ENGINE: Optional[OcrEngine] = None


def get_engine(lang: str = "fr") -> OcrEngine:
    """Return a global singleton OcrEngine for the given language."""
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None or _GLOBAL_ENGINE.lang != lang:
        _GLOBAL_ENGINE = OcrEngine(lang=lang)
    return _GLOBAL_ENGINE


def read_text_from_patch(
    patch: PatchType,
    *,
    lang: str = "fr",
) -> tuple[Optional[str], float]:
    """Convenience wrapper around the global engine."""
    engine = get_engine(lang)
    return engine.read_text(patch)


def read_amount_from_patch(
    patch: PatchType,
    *,
    lang: str = "fr",
) -> tuple[Optional[float], float, str]:
    """Convenience wrapper for reading amounts from patches."""
    engine = get_engine(lang)
    return engine.read_amount(patch)
