from __future__ import annotations

import numpy as np
from PIL import Image

from objet.scanner.cards_recognition import TemplateIndex
from objet.scanner.scan import ScanTable


def test_extract_patch_rebases_profile_box_with_runtime_anchor_offset() -> None:
    scan = ScanTable.__new__(ScanTable)
    scan.screen_array = np.zeros((80, 80, 3), dtype=np.uint8)
    scan.runtime_region_offset = (10, 5)
    scan.screen_array[35:39, 30:34] = [12, 34, 56]

    patch = scan._extract_patch((20, 30, 4, 4), pad=0)

    assert patch.shape == (4, 4, 3)
    assert np.all(patch == [12, 34, 56])


def test_update_runtime_region_offset_from_anchor_and_reference_offset() -> None:
    scan = ScanTable.__new__(ScanTable)
    scan.table_capture = {"enabled": True}
    scan.capture_origin = (100, 50)
    scan.reference_offset = (30, 20)
    scan.anchor_box = (145, 77, 10, 10)

    scan._update_runtime_region_offset()

    assert scan.runtime_region_offset == (15, 7)


def test_template_set_uses_other_sets_for_missing_card_labels(tmp_path) -> None:
    _write_template(tmp_path / "hand" / "numbers" / "A" / "a.png")
    _write_template(tmp_path / "hand" / "suits" / "spades" / "spades.png")
    _write_template(tmp_path / "board" / "numbers" / "6" / "six.png")
    _write_template(tmp_path / "board" / "suits" / "hearts" / "hearts.png")

    index = TemplateIndex(tmp_path)
    index.load()

    numbers, suits = index.get_templates("hand", include_fallback_sets=True)

    assert set(numbers) == {"A", "6"}
    assert set(suits) == {"spades", "hearts"}

    strict_numbers, strict_suits = index.get_templates("hand")
    assert set(strict_numbers) == {"A"}
    assert set(strict_suits) == {"spades"}


def _write_template(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (2, 2), color=255).save(path)
