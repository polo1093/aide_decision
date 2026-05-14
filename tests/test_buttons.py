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
            Button(enabled=True, value=2.0),
        ]
    )

    assert buttons.min_value() == 2.0


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
