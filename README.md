# Aide Décision

Assistant expérimental d'aide à la décision pour une table de poker en ligne.

Le projet capture l'écran, retrouve la table, lit les cartes, le pot, les joueurs et les boutons d'action, puis affiche une recommandation simple (`CHECK`, `CALL`, `FOLD`, `RAISE` ou `WAIT`) avec les métriques utiles.

## Objectif

L'application sert à analyser l'état courant d'une table, pas à jouer automatiquement.

Elle combine :

- capture écran et détection de table ;
- reconnaissance des cartes par templates ;
- OCR pour les montants et textes de boutons ;
- suivi de l'état de la main ;
- calcul d'équité via simulation Monte Carlo ;
- décision basée sur l'équité, le coût à payer et les boutons disponibles.

Le mode optionnel `pokercharts` intègre des ranges préflop statiques portées
depuis `AHTOOOXA/poker-charts` (licence MIT). Seules les données de charts
locales sont reprises: les leaderboards, scripts de scraping, données joueurs
et assets d'interface ne sont pas intégrés. Ces charts doivent rester un outil
d'étude hors table et leur usage doit respecter les règles de la plateforme.

## Philosophie

Le code doit rester lisible et explicite. Les erreurs de configuration ou de programmation doivent rester visibles.

En revanche, les erreurs normales de scan en live ne doivent pas arrêter l'application. Par exemple, une carte mal reconnue, un board incomplet pendant une frame, ou une table temporairement introuvable doivent produire un `SKIP` dans les logs plutôt qu'une erreur bloquante.

## Installation

Pré-requis :

- Windows recommandé, car le projet utilise la capture écran et PyAutoGUI ;
- Python 3.11 testé dans l'environnement local ;
- un profil de table dans `config/<jeu>/coordinates.json`.

Créer puis activer un environnement virtuel :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

EasyOCR peut télécharger ses modèles au premier lancement.

## Lancement

Lister les profils disponibles :

```powershell
.\.venv\Scripts\python.exe launch.py --list-games
```

Lancer l'interface :

```powershell
.\.venv\Scripts\python.exe launch.py --game PMU --interval 1000
```

Choisir un moteur de décision optionnel :

```powershell
.\.venv\Scripts\python.exe launch.py --game PMU --decision-mode pokercharts
```

Faire un seul scan depuis le terminal :

```powershell
.\.venv\Scripts\python.exe launch.py --game PMU --snapshot
```

Dans l'interface, le menu **Outils** permet de lancer les étapes de calibration et validation sans retaper les commandes.

## Workflow De Calibration

Le profil `PMU` est stocké dans `config/PMU/`. Les coordonnées, templates et captures d'entrainement y sont associés.

Pipeline rapide avec une vidéo OBS :

```powershell
.\.venv\Scripts\python.exe scripts\quick_setup.py --game PMU --video "C:\captures\session.mp4"
```

Étapes principales :

1. Éditer les zones à scanner.
2. Extraire des frames depuis une vidéo.
3. Identifier et labelliser les cartes manquantes.
4. Valider la reconnaissance sur la vidéo.

Commandes utiles :

```powershell
.\.venv\Scripts\python.exe scripts\quick_setup.py --game PMU --skip-capture --skip-identify --skip-capture-validation
.\.venv\Scripts\python.exe scripts\Crop_Video_Frames.py --game-dir config\PMU --video "C:\captures\session.mp4"
.\.venv\Scripts\python.exe scripts\identify_card.py --game PMU
.\.venv\Scripts\python.exe scripts\capture_cards.py --game PMU --game-dir config\PMU --video "C:\captures\session.mp4"
```

## Architecture

```text
launch.py
  -> Controller
      -> Game
          -> Table
              -> ScanTable
              -> CardsState / Players / Buttons / Pot
          -> Etat
              -> calcul équité, EV, call max
      -> Decision
          -> recommandation affichée dans l'UI
```

Modules principaux :

- `objet/services/controller.py` : orchestre un cycle complet et prépare l'état affichable.
- `objet/services/game.py` : maintient l'état stable de la main, détecte les nouvelles parties et calcule les métriques.
- `objet/services/table.py` : déclenche les scans et remplit les entités de table.
- `objet/services/decision.py` : transforme les métriques et boutons en décision.
- `objet/scanner/scan.py` : capture écran, recherche de table et scan des zones.
- `objet/scanner/cards_recognition.py` : reconnaissance des cartes par templates.
- `objet/scanner/amount_ocr.py` : OCR des montants et textes.
- `objet/entities/` : cartes, joueurs et boutons.
- `scripts/` : outils de calibration, labellisation et validation.

## Logs Et Dépannage

Les logs sont écrits dans `logs/`.

Fichiers utiles :

- `logs/app.log` : log applicatif courant ;
- `logs/interface_*.log` : session d'interface ;
- `logs/errors/` : captures liées aux erreurs bloquantes.

Lignes fréquentes :

- `SKIP table_introuvable` : l'ancre de table n'a pas été retrouvée ;
- `SKIP calcul raison=scan_board_incoherent` : scan partiel du board ignoré ;
- `SKIP calcul raison=cartes_dupliquees` : reconnaissance incohérente, souvent une couleur mal lue ;
- `DECISION action=...` : décision finale du cycle.

Pour suivre les erreurs :

```powershell
Select-String -Path logs\*.log -Pattern "ERROR|Traceback|SKIP calcul|DECISION"
```

## Tests

Lancer toute la suite :

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests importants :

- `tests/test_game.py` : suivi de main, nouvelle partie, calculs et scans incohérents ;
- `tests/test_decision.py` : logique de décision ;
- `tests/test_buttons.py` : interprétation des boutons, notamment priorité au `check` ;
- `tests/test_cards_recognition.py` : reconnaissance et overlays ;
- `tests/test_launch_tools.py` : commandes générées par le menu outils.

## Limites

Le projet dépend fortement :

- de la résolution écran ;
- de la stabilité visuelle du site ;
- de la qualité des templates de cartes ;
- de la précision OCR.

Après un changement d'interface, de zoom, de résolution ou de thème visuel, il faut probablement refaire une calibration.

## Statut

Projet personnel en évolution active. Les parties les plus sensibles sont la calibration, la reconnaissance des cartes et la robustesse des scans live.
