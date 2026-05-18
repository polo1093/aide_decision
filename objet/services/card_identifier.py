#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
card_identifier.py — service d’identification incrémentale des cartes.

- Utilise le dataset `config/<game>/cards/` via TemplateIndex.
- Tente une reco par gabarits.
- Si les deux (valeur + couleur) sont fiables (>= strict) → retour direct, sans UI.
- Sinon, si interactive=True :
    * ouvre un mini-dialog Tk/CustomTkinter,
    * ne demande QUE la partie inconnue (valeur OU couleur),
    * enregistre les patches rognés sous `cards/`,
    * met à jour l’index dans la foulée (effet immédiat sur les cartes suivantes).

API principale :
    CardIdentifier.identify_from_patches(...)
    CardIdentifier.identify_from_table(...)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple
import itertools
import time
import sys

# ajoute le VRAI project root: .../aide_decission
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

from objet.scanner.cards_recognition import (
    ROOT_TEMPLATE_SET,
    TemplateIndex,
    is_cover_me_cards,
    is_card_present,
    recognize_card_observation,
    trim_card_patch,
)

# Si dans ton projet CardPatch/collect_card_patches viennent de _utils, adapte ce import :
from scripts._utils import CardPatch, collect_card_patches  # ajuste si besoin

DEFAULT_NUMBERS: Sequence[str] = (
    "?",
    "A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2",
)
DEFAULT_SUITS: Sequence[str] = ("?", "spades", "hearts", "diamonds", "clubs")


def _trim(img: Image.Image, border: int) -> Image.Image:
    return trim_card_patch(img, border)


def _make_preview(num_img: Image.Image, suit_img: Image.Image) -> Image.Image:
    """Empile number/suit verticalement pour l'UI, avec zoom lisible."""
    num_w, num_h = num_img.size
    suit_w, suit_h = suit_img.size
    width = max(num_w, suit_w)
    spacer = 6
    preview = Image.new("RGB", (width, num_h + suit_h + spacer), "#f0f0f0")
    preview.paste(num_img, ((width - num_w) // 2, 0))
    preview.paste(suit_img, ((width - suit_w) // 2, num_h + spacer))
    scale = max(1, min(3, 120 // max(1, preview.height)))
    if scale > 1:
        preview = preview.resize(
            (preview.width * scale, preview.height * scale),
            Image.Resampling.NEAREST,
        )
    return preview


@dataclass
class IdentifyResult:
    number: str
    suit: str
    meta: Dict[str, object]


class _SingleCardDialog:
    """
    Boîte de dialogue minimale pour compléter uniquement la partie inconnue.

    - missing_number / missing_suit contrôlent quels champs sont affichés.
    - suggested_* servent de valeur pré-sélectionnée dans les menus.
    """

    def __init__(
        self,
        number_img: Image.Image,
        suit_img: Image.Image,
        *,
        missing_number: bool,
        missing_suit: bool,
        number_choices: Sequence[str],
        suit_choices: Sequence[str],
        suggested_number: Optional[str] = None,
        suggested_suit: Optional[str] = None,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Identifier la carte")
        self.root.geometry("560x480")

        # action: "ok" | "cancel" | "delete"
        self.action: str = "cancel"
        self.result: Optional[Tuple[str, str]] = None

        # Valeurs par défaut (y compris si le champ n’est pas affiché)
        self.number_var = tk.StringVar(
            value=(suggested_number or (number_choices[0] if number_choices else "?"))
        )
        self.suit_var = tk.StringVar(
            value=(suggested_suit or (suit_choices[0] if suit_choices else "?"))
        )

        top = ctk.CTkFrame(self.root)
        top.pack(fill="both", expand=True, padx=12, pady=12)

        preview = _make_preview(number_img, suit_img)
        self.photo = ImageTk.PhotoImage(preview)
        self.img_lbl = ctk.CTkLabel(top, image=self.photo, text="", compound="top")
        self.img_lbl.pack(pady=8)

        form = ctk.CTkFrame(top)
        form.pack(pady=8)

        row = 0
        if missing_number:
            ctk.CTkLabel(form, text="Valeur").grid(row=row, column=0, padx=8, pady=6)
            self.num_menu = ctk.CTkOptionMenu(
                form,
                values=list(number_choices) or ["?"],
                variable=self.number_var,
            )
            self.num_menu.grid(row=row, column=1, padx=8, pady=6)
            row += 1
        if missing_suit:
            ctk.CTkLabel(form, text="Couleur").grid(row=row, column=0, padx=8, pady=6)
            self.suit_menu = ctk.CTkOptionMenu(
                form,
                values=list(suit_choices) or ["?"],
                variable=self.suit_var,
            )
            self.suit_menu.grid(row=row, column=1, padx=8, pady=6)
            row += 1

        btns = ctk.CTkFrame(top)
        btns.pack(pady=10)

        ctk.CTkButton(btns, text="Valider", command=self._on_save).pack(
            side="left", padx=8
        )
        ctk.CTkButton(btns, text="Annuler", command=self._on_cancel).pack(
            side="left", padx=8
        )
        # Nouveau bouton Delete
        ctk.CTkButton(btns, text="Delete", command=self._on_delete).pack(
            side="left", padx=8
        )

    def run(self) -> Optional[Tuple[str, str]]:
        self.root.mainloop()
        return self.result

    def _on_save(self) -> None:
        self.action = "ok"
        self.result = (
            self.number_var.get().strip() or "?",
            self.suit_var.get().strip() or "?",
        )
        self.root.destroy()

    def _on_cancel(self) -> None:
        self.action = "cancel"
        self.result = None
        self.root.destroy()

    def _on_delete(self) -> None:
        # signale qu’on veut supprimer la capture
        self.action = "delete"
        self.result = None
        self.root.destroy()


class CardIdentifier:
    """
    Service réutilisable d’identification incrémentale (par patches ou par table).

    - threshold : score à partir duquel on considère que la valeur/couleur est "connue"
                  (on ne la redemande pas à l’utilisateur).
    - strict    : score à partir duquel on autoskip complètement la carte
                  (pas d’UI si les deux >= strict).
    """

    def __init__(
        self,
        game_dir: Path | str,
        *,
        trim: int = 6,
        threshold: float = 0.92,
        strict: float = 0.985,
        number_choices: Sequence[str] = DEFAULT_NUMBERS,
        suit_choices: Sequence[str] = DEFAULT_SUITS,
    ) -> None:
        self.game_dir = Path(game_dir)
        self.cards_root = self.game_dir / "cards"
        self.trim = int(trim)
        self.threshold = float(threshold)
        self.strict = float(strict)

        self.number_choices = list(number_choices)
        self.suit_choices = list(suit_choices)

        self.idx = TemplateIndex(self.cards_root)
        self.idx.load()

        self._counter = itertools.count(1)
        self._last_template_set: Optional[str] = None

    # ---------- helpers internes ----------

    def _normalise_template_set(self, template_set: Optional[str]) -> Optional[str]:
        """Choisit un set de templates cohérent quand le patch n’en indique pas."""
        if template_set:
            return template_set
        if self._last_template_set:
            return self._last_template_set
        default = self.idx.default_set
        return None if default == ROOT_TEMPLATE_SET else default

    def _save_if_missing(
        self,
        num_img: Image.Image,
        suit_img: Image.Image,
        number_label: str,
        suit_label: str,
        save_number: bool,
        save_suit: bool,
        base_key: str,
        template_set: Optional[str],
    ) -> None:
        ts = int(time.time())
        idx = next(self._counter)
        base = f"{base_key}_{ts}_{idx:04d}"

        resolved_set = self._normalise_template_set(template_set)
        self._last_template_set = resolved_set

        if resolved_set:
            root = self.cards_root / resolved_set
        else:
            root = self.cards_root

        if save_number:
            p = root / "numbers" / number_label / f"{base}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            num_img.save(p)
        if save_suit:
            p = root / "suits" / suit_label / f"{base}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            suit_img.save(p)

    def _update_index(
        self,
        label: str,
        img: Image.Image,
        *,
        is_number: bool,
        template_set: Optional[str],
    ) -> None:
        resolved_set = self._normalise_template_set(template_set)
        self.idx.append_template(resolved_set, label, img, is_number=is_number)

    # ---------- API patches ----------

    def identify_from_patches(
        self,
        number_patch: Image.Image,
        suit_patch: Image.Image,
        *,
        base_key: str = "live",
        template_set: Optional[str] = None,
        interactive: bool = True,
        force_all: bool = False,
    ) -> IdentifyResult:
        # 1) Trim + reco
        tpl_set = self._normalise_template_set(template_set)

        observation = recognize_card_observation(
            number_patch,
            suit_patch,
            self.idx,
            template_set=tpl_set,
            trim=self.trim,
        )

        num_s = observation.value
        suit_s = observation.suit
        score_num = float(observation.value_score)
        score_suit = float(observation.suit_score)

        # Niveaux de confiance
        num_known = bool(num_s) and score_num >= self.threshold
        suit_known = bool(suit_s) and score_suit >= self.threshold
        num_strict = bool(num_s) and score_num >= self.strict
        suit_strict = bool(suit_s) and score_suit >= self.strict

        # 1.a Autoskip "dur" : on est très sûr sur les deux
        if num_strict and suit_strict and not force_all:
            return IdentifyResult(
                num_s,
                suit_s,
                {
                    "source": "auto",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        trimmed_number = _trim(number_patch, self.trim)
        trimmed_suit = _trim(suit_patch, self.trim)

        # Partie manquante = en-dessous du seuil "connue" (ou si force_all)
        missing_number = (not num_known) or force_all
        missing_suit = (not suit_known) or force_all

        # 1.b Mode non interactif → on ne montre jamais d'UI
        if not interactive:
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "guess",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        # 1.c IMPORTANT : si rien à demander → surtout ne pas ouvrir de popup vide
        if not (missing_number or missing_suit):
            # "auto-soft" : on fait confiance au modèle, même si ce n'est pas >= strict
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "auto-soft",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        # 2) Ici on a vraiment quelque chose à compléter → on ouvre une mini-UI
        dialog = _SingleCardDialog(
            trimmed_number,
            trimmed_suit,
            missing_number=missing_number,
            missing_suit=missing_suit,
            number_choices=self.number_choices,
            suit_choices=self.suit_choices,
            suggested_number=num_s,
            suggested_suit=suit_s,
        )
        out = dialog.run()
        action = dialog.action  # "ok" | "cancel" | "delete"

        # 2.a Delete → laisse identify_card.py gérer la suppression physique
        if action == "delete":
            return IdentifyResult(
                "?", "?",
                {
                    "source": "delete",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        if out is None:
            # Annulé → renvoyer la meilleure info disponible
            return IdentifyResult(
                num_s if num_s else "?",
                suit_s if suit_s else "?",
                {
                    "source": "cancel",
                    "score_number": score_num,
                    "score_suit": score_suit,
                },
            )

        lab_num, lab_suit = out

        save_number = missing_number and lab_num not in {"", "?"}
        save_suit = missing_suit and lab_suit not in {"", "?"}

        # 3) Sauvegarde + MAJ index en temps réel
        if save_number or save_suit:
            self._save_if_missing(
                trimmed_number,
                trimmed_suit,
                lab_num,
                lab_suit,
                save_number,
                save_suit,
                base_key,
                tpl_set,
            )
            if save_number:
                self._update_index(
                    lab_num,
                    trimmed_number,
                    is_number=True,
                    template_set=tpl_set,
                )
            if save_suit:
                self._update_index(
                    lab_suit,
                    trimmed_suit,
                    is_number=False,
                    template_set=tpl_set,
                )

        final_num = lab_num or (num_s if num_s else "?")
        final_suit = lab_suit or (suit_s if suit_s else "?")

        return IdentifyResult(
            final_num,
            final_suit,
            {
                "source": "labeled",
                "score_number": score_num,
                "score_suit": score_suit,
            },
        )

    # ---------- API pratique par image de table ----------

    def identify_from_table(
        self,
        table_img: Image.Image,
        regions: Dict[str, object],
        base_key: str,
        *,
        interactive: bool = True,
        force_all: bool = False,
    ) -> IdentifyResult:
        pairs = collect_card_patches(table_img.convert("RGB"), regions, pad=0)
        card_patch = pairs.get(base_key)
        if not card_patch:
            return IdentifyResult("?", "?", {"source": "error", "reason": "region-missing"})

        tpl_set = card_patch.template_set

        # Overlay HOLD / FOLD → on considère la carte vide
        tpl_lower = (tpl_set or "").lower()
        if "hand" in tpl_lower and is_cover_me_cards(card_patch.number):
            return IdentifyResult("?", "?", {"source": "empty", "reason": "hold-overlay"})

        # Test présence carte
        if not is_card_present(card_patch.number, threshold=215, min_ratio=0.04):
            return IdentifyResult("?", "?", {"source": "empty", "reason": "no-card"})

        return self.identify_from_patches(
            card_patch.number,
            card_patch.suit,
            base_key=base_key,
            template_set=tpl_set,
            interactive=interactive,
            force_all=force_all,
        )
