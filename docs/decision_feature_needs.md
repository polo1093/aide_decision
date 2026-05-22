# Besoins du moteur de decision

Ce document liste les donnees qui rendent la decision plus fiable. Il sert de guide pour les prochaines evolutions du scan et de la calibration.

## Deja utilise

- Cartes hero normalisees en `PokerCard`.
- Board coherent: 0, 3, 4 ou 5 cartes.
- Pot courant.
- Montant a payer (`to_call`) lu depuis les boutons.
- Boutons actifs: `check`, `paie`, `mise`, `relance`, `fold`, `all-in`.
- Equity table et equity 1v1.
- Profils adverses simples issus des etats joueurs et de l'historique.
- Position hero manuelle: `UTG`, `MP`, `CO`, `BTN`, `SB`, `BB`.

## Priorite haute

- Detection automatique de la position hero, ou calibration fiable du bouton dealer/blinds.
- Stack hero et stacks adverses fiables, pas seulement les montants visibles des autres joueurs.
- Taille effective du stack contre le joueur qui mise.
- Historique d'action de la main courante: open, limp, call, 3-bet, check, bet, raise.
- Identification de l'agresseur courant et de sa position.

## Priorite moyenne

- Nombre de joueurs encore a parler preflop.
- Distinction claire entre pot cash-game et blindes/tournoi.
- Taille de mise adverse en ratio pot, avec confiance OCR.
- Detection des streets transitoires pour eviter les decisions sur une frame incomplete.
- Score de confiance par carte, bouton, pot et montant a payer.

## Priorite basse

- Ranges differentes selon contexte: RFI, defense BB, call vs open, 3-bet, shove short stack.
- Board texture explicite: flush draw, straight draw, paired board, monotone/two-tone.
- Memoire plus fine par joueur: VPIP, PFR, 3-bet, fold to c-bet.
- Mode review qui explique la decision avec les inputs utilises.

## Regle d'integration

Une nouvelle feature de decision doit arriver avec un test cible. Si la feature depend du scan live et n'est pas testable directement, extraire d'abord la logique pure dans un service testable.
