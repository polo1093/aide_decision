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
- `decision_engine_version`: `decision_engine_v2`
- `legacy_rules_version`: `legacy_rules_v2`
- `decision_engine_fix_id`: `premium_made_hand_never_fold_2026_05_24`
- `decision_engine_fix_date`: `2026-05-24`
- `git_commit`: short Git commit id, suffixed with `-dirty` when local files are
  modified

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
- `amount_unit`: currently `big_blind`
- `amount_unit_value`: raw value of one current big blind in the scanned table
  unit
- `amount_unit_source`: where the unit came from (`explicit_current_big_blind`,
  `starting_pot`, `preflop_to_call`, `preflop_small_blind_to_call`, or
  `preflop_button_value`)
- `pot`
- `pot_bb`
- `to_call`
- `to_call_bb`
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
- `ev_bb`
- `call_max`
- `call_max_bb`

Money fields ending in `_bb` are normalized in current big blinds and are the
preferred model inputs. Raw money fields (`pot`, `to_call`, stack values, button
values, `ev`, `call_max`) are kept for audit/debug only so centime, euro, and
tournament-chip tables do not teach different scales for the same poker spot.
Raw strings such as card labels and button states should be encoded outside the
live application.

`buttons[].value_bb`, `players[].stack_bb`, and `players[].stack_start_bb` use
the same unit.

### labels

Decision outputs and comparison fields.

- `legacy_action`
- `legacy_reason`
- `legacy_raise_amount`
- `legacy_raise_amount_bb`
- `ml_action`
- `ml_confidence`
- `final_action`
- `fallback_reason`
- `label_valid`
- `label_exclusion_reason`
- `known_bug_risk`

For `ml_dataset_v1`, `ml_action`, `ml_confidence`, and `fallback_reason` are
usually `null` because no ML model is connected yet. `final_action` is the
legacy action while the runtime mode remains `legacy`.

`label_valid` is the training gate for the legacy label. It is `false` when the
snapshot has blocking quality flags, when the action is not trainable (`WAIT`),
or when the engine version is known to carry historical bug risk.
`label_exclusion_reason` stores the first blocking reason. `known_bug_risk`
must be treated as a hard exclusion unless the row has been manually reviewed.

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
- `amount_unit_missing`
- `pot_to_call_incoherent`
- `buttons_incoherent`
- `hero_position_low_confidence`
- `street_transient`
- `usable_for_training`

`usable_for_training` describes scan/data quality. It is not sufficient on its
own; training exports must also require `labels.label_valid == true`.

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

## Label Versioning Rules

Do not mix legacy logs generated before the `premium_made_hand_never_fold`
corrective rule with new logs. Old snapshots either lack
`metadata.decision_engine_fix_id` or have a different
`decision_engine_version`/`legacy_rules_version`. They must be excluded from ML
training by default.

The known historical bug was a legacy fold path that could fold premium made
hands when noisy equity or `Call_max` made the call look negative. This is most
dangerous on postflop spots where hero already has a very strong made hand,
especially full house or better. Labels from pre-fix logs can still be useful
for manual review or regression analysis, but not as trusted supervised labels.

Minimum filter for future exports:

```text
type == "ml_decision_snapshot"
metadata.decision_engine_version == "decision_engine_v2"
metadata.legacy_rules_version == "legacy_rules_v2"
metadata.decision_engine_fix_id == "premium_made_hand_never_fold_2026_05_24"
quality_flags.usable_for_training == true
labels.label_valid == true
labels.known_bug_risk == false
```

## Contaminated Log Strategy

For now, do not rewrite old telemetry files. The safer strategy is to keep raw
logs immutable and apply an export-time exclusion script later.

Recommended script shape:

```text
read logs/telemetry/**/hands/*.jsonl
keep only ml_decision_snapshot rows with the exact engine/rules/fix ids above
drop rows with missing version metadata
drop rows where labels.label_valid is not true
optionally emit a review report for old postflop FOLD rows with premium made hands
```

If old logs must be salvaged, first generate a review list of suspicious rows
instead of relabelling automatically.
