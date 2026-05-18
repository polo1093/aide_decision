from objet.scanner.amount_ocr import OcrEngine


def test_parse_amount_accepts_space_grouped_thousands() -> None:
    engine = OcrEngine()

    value = engine._parse_amount_from_text("$4 980", allow_comma=True, allow_dot=True)

    assert value == 4980.0


def test_parse_amount_uses_largest_amount_when_total_and_bets_are_visible() -> None:
    engine = OcrEngine()

    value = engine._parse_amount_from_text("Total: $0 Bets: $70", allow_comma=True, allow_dot=True)

    assert value == 70.0


def test_parse_amount_fixes_dollar_read_as_five_before_grouped_stack() -> None:
    engine = OcrEngine()

    value = engine._parse_amount_from_text("54 980", allow_comma=True, allow_dot=True)

    assert value == 4980.0


def test_parse_amount_fixes_dollar_read_as_separate_five_before_grouped_stack() -> None:
    engine = OcrEngine()

    value = engine._parse_amount_from_text("5 11 840", allow_comma=True, allow_dot=True)

    assert value == 11840.0


def test_parse_amount_keeps_ungrouped_values_conservative() -> None:
    engine = OcrEngine()

    value = engine._parse_amount_from_text("530", allow_comma=True, allow_dot=True)

    assert value == 530.0
