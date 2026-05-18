# Interface Profile Method

This note is for future profile reconstruction work. Keep it separate from the user README: it is an operator checklist for adding or repairing a `config/<game>` interface from captures.

## Inputs

Put these files in `config/<game>/`:

- `test_crop.png`: full-screen capture.
- `test_crop_result.png`: crop of the table/window that should be tracked.
- `anchor.png`: small stable visual anchor inside the table/window.
- Optional video: `.mkv`, `.mp4`, `.avi`, or `.mov`.

For best results, the video should include preflop, flop, turn, river, visible hero cards, visible action buttons, and a few opponent states.

## Main Workflow

1. Infer capture geometry and seed known regions if a preset exists:

```powershell
.\.venv\Scripts\python.exe scripts\rebuild_profile.py --game PokerTH --preset pokerth --force-preset
```

For a new unknown interface, start without a preset:

```powershell
.\.venv\Scripts\python.exe scripts\rebuild_profile.py --game NouveauJeu
```

2. Sample the video into useful table frames:

```powershell
.\.venv\Scripts\python.exe scripts\sample_video_profile.py --game PokerTH
```

Outputs go to `config/<game>/entrainement/profile_samples/`.

3. Draw a region overlay:

```powershell
.\.venv\Scripts\python.exe scripts\profile_overlay.py --game PokerTH
```

Inspect `config/<game>/debug_overlay.png`.

4. Extract action/state templates from a video.

Use a preset when available:

```powershell
.\.venv\Scripts\python.exe scripts\extract_action_templates.py --game PokerTH --preset pokerth
```

Or pass manual crop specs:

```powershell
.\.venv\Scripts\python.exe scripts\extract_action_templates.py --game NouveauJeu --template check.png:160:98,149,158,166
```

The crop box is relative to the table crop, not full screen.

5. Validate the profile:

```powershell
.\.venv\Scripts\python.exe scripts\validate_profile.py --game PokerTH --overlay
```

The validator checks geometry, region presence, region bounds, action templates, object construction, and a rough visible-card guess.

## When Reconstructing Manually

Use sampled frames and overlays to adjust `coordinates.json`. Keep region coordinates absolute screen coordinates. `table_capture.origin`, `bounds`, `size`, and `ref_offset` allow tools to rebase onto table crops.

Important region groups:

- Cards: `player_card_*_number`, `player_card_*_symbol`, `board_card_*_number`, `board_card_*_symbol`.
- Money: `pot`, `fond`, `player_money_J1..J5`.
- Buttons: `button_1..button_3`.
- Player states: `player_state_me`, `player_state_J1..J5`.
- Optional names: `player_name_J1..J5`.

## Known PokerTH Notes

PokerTH displays English buttons. The runtime normalizes:

- `Call` -> `paie`
- `Raise` -> `relance`
- `Bet` -> `mise`
- `All-In` -> `all-in`

OCR amounts may contain spaces (`$4 980`) or multiple values (`Total: $0 Bets: $70`); the amount parser is expected to handle both.

## Completion Criteria

A profile is ready when:

- `validate_profile.py --overlay` returns `status: OK` or only acceptable warnings.
- `debug_overlay.png` or `validation_overlay.png` visually aligns on table samples.
- Action templates exist for states used by the scanner.
- `pytest` passes.
