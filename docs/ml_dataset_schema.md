# ML Dataset Schema

This document describes the first stable event shape used to collect live poker
decision data for offline machine learning experiments. The application still
uses the legacy decision engine at runtime; this schema only adds structured
observations for later export.

## Event

- `schema_version`: fixed string, `ml_dataset_v1`.
- `type`: fixed string, `ml_decision_snapshot`.
- `snapshot_id`: stable identifier for a scan cycle when available.
- `recorded_at`: UTC timestamp copied from telemetry.

## Storage Layout

Telemetry is grouped by runtime session so hand ids from separate executions do
not share the same JSONL files:

```text
logs/telemetry/<game>/sessions/<session_id>/hands/hand_<hand_id>.jsonl
logs/telemetry/<game>/sessions/<session_id>/players/<player>.jsonl
```

`session_id` is generated when `TelemetryRecorder` is created. It can also be
injected in tests or tools when deterministic paths are needed.

Unknown values must be serialized as `null`. The builder must not infer missing
game facts from defaults unless the runtime state already exposes them.

## Top-Level Sections

### metadata

Runtime context that identifies the source snapshot.

- `game`
- `hand_id`
- `scan_count`
- `street`
- `status`
- `decision_mode`
- `label_source`
- `new_party_state`

Initial values:

- `decision_mode`: `legacy`
- `label_source`: `legacy`

Future allowed values:

- `decision_mode`: `legacy`, `ml_shadow`, `ml_safe`
- `label_source`: `legacy`, `manual_review`, `solver_offline`, `simulation`

### features

Model input candidates based on values available in live play.

- `hero_cards`
- `board_cards`
- `hero_position`
- `player_start`
- `player_active`
- `pot`
- `to_call`
- `to_call_pot_ratio`
- `buttons`
- `buttons_active`
- `has_check`
- `has_call`
- `has_raise`
- `players`
- `opponent_profiles`
- `equity_table`
- `equity_1v1`
- `equity_required`
- `ev`
- `call_max`

The first model should use these as tabular features after offline encoding. Raw
strings such as card labels and button states should be encoded outside the live
application.

### labels

Decision outputs and comparison fields.

- `legacy_action`
- `legacy_reason`
- `legacy_raise_amount`
- `ml_action`
- `ml_confidence`
- `final_action`
- `fallback_reason`

For `ml_dataset_v1`, `ml_action`, `ml_confidence`, and `fallback_reason` are
usually `null` because no ML model is connected yet. `final_action` is the
legacy action while the runtime mode remains `legacy`.

### confidence

Confidence scores when available. Missing confidence remains `null`.

- `hero_cards_min`
- `board_cards_min`
- `pot_ocr`
- `to_call_ocr`
- `buttons_min`
- `hero_position`
- `player_count`

### quality_flags

Boolean guard rails used to filter training rows and decide future fallbacks.

- `hero_cards_uncertain`
- `board_uncertain`
- `opponent_count_uncertain`
- `pot_to_call_incoherent`
- `buttons_incoherent`
- `hero_position_low_confidence`
- `street_transient`
- `usable_for_training`

### debug

Non-model diagnostic data.

- `hero_scan_raw`
- `board_scan_raw`
- `hero_state_raw`
- `board_state_raw`
- `button_texts_raw`
- `target_button`
- `scan_status`
- `decision_reason`

Debug fields are useful for review and export validation, but should not be used
as direct model features unless explicitly promoted in a later schema version.
