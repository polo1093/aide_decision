"""Test helpers and environment shims for pytest."""
from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from typing import Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _install_cv2_stub() -> None:
    """Provide a tiny cv2 stub when OpenCV is unavailable."""

    if "cv2" in sys.modules:
        # Respect an existing installation (or another stub injected earlier).
        return

    module = types.ModuleType("cv2")
    module.COLOR_RGB2BGR = 0
    module.COLOR_BGR2RGB = 1
    module.COLOR_RGB2GRAY = 2
    module.COLOR_BGR2GRAY = 3
    module.TM_CCOEFF_NORMED = 5
    module.TM_SQDIFF = 6
    module.TM_SQDIFF_NORMED = 7
    module.CAP_PROP_FPS = 5
    module.__version__ = "0.0-tests"

    def cvtColor(arr: np.ndarray, code: int) -> np.ndarray:
        array = np.asarray(arr)
        if code in (module.COLOR_RGB2BGR, module.COLOR_BGR2RGB):
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            return array[..., ::-1].copy()
        if code == module.COLOR_RGB2GRAY:
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            r = array[..., 0].astype(float)
            g = array[..., 1].astype(float)
            b = array[..., 2].astype(float)
            gray = 0.2989 * r + 0.5870 * g + 0.1140 * b
            return gray.astype(array.dtype, copy=False)
        if code == module.COLOR_BGR2GRAY:
            if array.ndim < 3 or array.shape[2] < 3:
                return np.array(array, copy=True)
            b = array[..., 0].astype(float)
            g = array[..., 1].astype(float)
            r = array[..., 2].astype(float)
            gray = 0.1140 * b + 0.5870 * g + 0.2989 * r
            return gray.astype(array.dtype, copy=False)
        raise NotImplementedError(f"Unsupported conversion code: {code}")

    def matchTemplate(image: np.ndarray, template: np.ndarray, method: int = module.TM_CCOEFF_NORMED) -> np.ndarray:
        img = np.asarray(image, dtype=float)
        tpl = np.asarray(template, dtype=float)
        ih, iw = img.shape[:2]
        th, tw = tpl.shape[:2]
        if ih < th or iw < tw:
            raise ValueError("Template must be smaller than image.")
        out_h = ih - th + 1
        out_w = iw - tw + 1
        result = np.zeros((out_h, out_w), dtype=float)
        tpl_mean = tpl.mean()
        tpl_norm = tpl - tpl_mean
        tpl_denom = math.sqrt(float(np.sum(tpl_norm ** 2))) or 1.0
        tpl_energy = float(np.sum(tpl ** 2)) or 1.0
        for y in range(out_h):
            for x in range(out_w):
                patch = img[y : y + th, x : x + tw]
                if method == module.TM_CCOEFF_NORMED:
                    patch_mean = patch.mean()
                    patch_norm = patch - patch_mean
                    denom = math.sqrt(float(np.sum(patch_norm ** 2))) * tpl_denom
                    denom = denom or 1.0
                    score = float(np.sum(patch_norm * tpl_norm)) / denom
                    result[y, x] = score
                elif method in (module.TM_SQDIFF, module.TM_SQDIFF_NORMED):
                    diff = patch - tpl
                    mse = float(np.mean(diff ** 2))
                    if method == module.TM_SQDIFF:
                        result[y, x] = mse
                    else:
                        norm = float(np.mean(patch ** 2) + tpl_energy)
                        norm = norm or 1.0
                        result[y, x] = mse / norm
                else:
                    raise NotImplementedError(f"Unsupported matchTemplate method: {method}")
        return result

    def minMaxLoc(arr: np.ndarray) -> Tuple[float, float, Tuple[int, int], Tuple[int, int]]:
        array = np.asarray(arr)
        min_idx = int(array.argmin())
        max_idx = int(array.argmax())
        min_val = float(array.flat[min_idx])
        max_val = float(array.flat[max_idx])
        if array.ndim == 2:
            height, width = array.shape
            min_loc = (min_idx % width, min_idx // width)
            max_loc = (max_idx % width, max_idx // width)
        else:
            min_loc = (0, 0)
            max_loc = (0, 0)
        return min_val, max_val, min_loc, max_loc

    class VideoCapture:
        def __init__(self, *_, **__):
            raise RuntimeError("cv2.VideoCapture is unavailable in the test stub.")

        def read(self):  # pragma: no cover - stub
            return False, None

        def release(self) -> None:  # pragma: no cover - stub
            return None

        def get(self, *_):  # pragma: no cover - stub
            return 0.0

    module.cvtColor = cvtColor
    module.matchTemplate = matchTemplate
    module.minMaxLoc = minMaxLoc
    module.VideoCapture = VideoCapture

    sys.modules["cv2"] = module


_install_cv2_stub()
