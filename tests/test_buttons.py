"""Tests for button state parsing."""
from __future__ import annotations

from objet.entities.buttons import Button, Buttons


def test_one_is_activate_is_false_when_all_buttons_disabled() -> None:
    buttons = Buttons(button=[Button(enabled=False), Button(enabled=False)])

    assert buttons.one_is_activate() is False


def test_one_is_activate_is_true_when_one_button_enabled() -> None:
    buttons = Buttons(button=[Button(enabled=False), Button(enabled=True)])

    assert buttons.one_is_activate() is True


def test_apply_scan_disables_unknown_button_text() -> None:
    button = Button(enabled=True, texte="paie 1.00", etat="paie", value=1.0)

    button.apply_scan("texte inconnu")

    assert button.is_activate() is False
    assert button.etat == ""
    assert button.value == 0.0


def test_min_value_ignores_disabled_buttons() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=False, value=0.5),
            Button(enabled=True, etat="paie", value=2.0),
        ]
    )

    assert buttons.min_value() == 2.0


def test_min_value_handles_large_chip_amounts() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="relance", value=4760.0),
            Button(enabled=True, etat="paie", value=4520.0),
            Button(enabled=True, etat="fold", value=0.0),
        ]
    )

    assert buttons.min_value() == 4520.0


def test_check_button_makes_min_value_free_even_with_bet_button() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="check", value=0.0),
            Button(enabled=True, etat="mise", value=0.02),
        ]
    )

    assert buttons.has_free_action() is True
    assert buttons.has_aggressive_action() is True
    assert buttons.min_value() == 0.0


def test_min_value_ignores_aggressive_buttons_when_call_is_absent() -> None:
    buttons = Buttons(
        button=[
            Button(enabled=True, etat="fold", value=0.0),
            Button(enabled=True, etat="mise", value=120.0),
            Button(enabled=True, etat="relance", value=240.0),
        ]
    )

    assert buttons.has_call_action() is False
    assert buttons.min_value() == 0.0


def test_apply_scan_accepts_english_pokerth_buttons() -> None:
    button = Button()

    button.apply_scan("F2 Call $20")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 20.0


def test_apply_scan_keeps_explicit_dollar_800_call_button() -> None:
    button = Button()

    button.apply_scan("call $800")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 800.0


def test_apply_scan_ignores_function_key_for_fold() -> None:
    button = Button()

    button.apply_scan("F1 Fold")

    assert button.is_activate() is True
    assert button.etat == "fold"
    assert button.value == 0.0


def test_apply_scan_keeps_all_in_distinct_from_call() -> None:
    button = Button()

    button.apply_scan("F4 All-In")

    assert button.is_activate() is True
    assert button.etat == "all-in"


def test_apply_scan_fixes_dollar_read_as_four_for_call_button() -> None:
    button = Button()

    button.apply_scan("call 410")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 10.0


def test_apply_scan_fixes_dollar_read_as_four_for_three_digit_call_button() -> None:
    button = Button()

    button.apply_scan("call 4200")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 200.0


def test_apply_scan_fixes_dollar_read_as_four_for_three_digit_raise_button() -> None:
    button = Button()

    button.apply_scan("raise 4360")

    assert button.is_activate() is True
    assert button.etat == "relance"
    assert button.value == 360.0


def test_apply_scan_fixes_dollar_read_as_eight_for_call_button() -> None:
    button = Button()

    button.apply_scan("call 840")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 40.0


def test_apply_scan_ignores_digits_embedded_in_ocr_words() -> None:
    button = Button()

    button.apply_scan("call s10o")

    assert button.is_activate() is True
    assert button.etat == "paie"
    assert button.value == 0.0


def test_apply_scan_fixes_grouped_all_in_amount() -> None:
    button = Button()

    button.apply_scan("F4 All-In 54 840")

    assert button.is_activate() is True
    assert button.etat == "all-in"
    assert button.value == 4840.0
