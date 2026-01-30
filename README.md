# aide de décision
Philosophie. 
Très important : si une fonction n'a pas le bon argument, ne peut pas charger une image, ne reçoit pas les bonnes choses en entrée, et bien je veux pas faire une exception. Je veux que le programme plante, crache.

Je veux que le code soit simple à comprendre et puisse cracher si il y a un truc qui ne fonctionne pas. Je veux pas d'exceptions qui me cachent un problème. 

## Architecture globale

L’application est structurée autour d’un noyau `Game` qui orchestre l’état de la table, des joueurs, des boutons et des cartes, ainsi que la logique de partie et de décision.

### 1. Game

1.1. **Table**  
&nbsp;&nbsp;&nbsp;&nbsp;1.1.1. `scan_table`  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1.1.1.1. (ajout du scan *fond* et *pot* en OCR)  
&nbsp;&nbsp;&nbsp;&nbsp;1.1.2. `Card_state`  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1.1.2.1. `Card` (regrouper toutes les classes d’entities carte en une seule)  
&nbsp;&nbsp;&nbsp;&nbsp;1.1.3. `Buttons_state`  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1.1.3.1. `Button`  
&nbsp;&nbsp;&nbsp;&nbsp;1.1.4. `Player_state`  
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;1.1.4.1. `Player`

1.2. **Party**  
&nbsp;&nbsp;&nbsp;&nbsp;1.2.1. Gestion des états de la partie (phase de jeu, street, main en cours, historique, etc.)

1.3. **Décission**  
&nbsp;&nbsp;&nbsp;&nbsp;Moteur de décision basé sur l’état courant du `Game` / `Table` / `Player_state` (rules, heuristiques, modèle ML, etc.)

### 2. Contrôleur
- joue le rôle d’orchestrateur haut niveau :  
  - création et cycle de vie de `Game`,  
  - coordination entre  `Game` et `Décission`,  
  - gestion des événements externes (UI, hotkeys, logs, etc.).

### 3. Afficheur / `launch.py` + Thinker

- `launch.py` sert de point d’entrée applicatif.  
- Rôle principal :  
  - initialiser le “thinker” (boucle principale d’analyse/decision),  
  - câbler l’affichage (console, UI, overlay…) avec l’état de `Game` / `Table`,  
  - piloter la fréquence des scans (`scan_table`) et des décisions.

Ce schéma sert de référence pour l’implémentation et pour organiser les modules Python (fichiers et packages) selon cette hiérarchie logique.


flowchart LR
  A[config/coordinates.json] --> B[Capture/Screen Grab] fait
  B --> C[Crop & Pré-traitement] fait
  C --> D[OCR / Matching] en cours
  D --> E[État du jeu] à faire
  E --> F[Moteur d'aide à la décision] à faire
  F --> G[Sorties: console/UI/overlay] en cours





To do list 

Réfaire une séance de capture avec OBS . 
Refaire les paramétrages et le crop de l'écran, et tout ça, les screen au bon endroit . 
Ajoutez les boutons et le fond. 
Tester l'OCR. 

Ajouter une fonction pour détecter un truc bizarre qui est affiché à l'écran. 
Pour ajouter une fonction pour détecter si c'est à nous de jouer ou pas. 




## Installation

1. Cloner le dépôt.
2. Installer Python 3.9 ou version supérieure.
3. Installer les dépendances :


## Utilitaires de calibration partagés

Les scripts de calibration (`capture_cards.py`, `identify_card.py`, `position_zones*.py`,
`zone_project.py`) s'appuient désormais sur un module commun `scripts/_utils.py`.
Ce module centralise :

- le chargement de `coordinates.json` (résolution des `templates`, conversion
  robuste des entiers) ;
- les fonctions de clamp et d'extraction d'images utilisées par les différents
  CLI/UI.

Les interfaces en ligne de commande existantes ne changent pas : les mêmes
options et arguments continuent de fonctionner, avec un comportement aligné
entre tous les outils.

## Avertissement

Ce projet est fourni à titre expérimental.
