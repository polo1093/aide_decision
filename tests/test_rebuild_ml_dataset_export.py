"""Tests for rebuilding the exported ML dataset."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.rebuild_ml_dataset_export import rebuild_export


def test_rebuild_export_writes_trainable_rows_with_big_blind_amounts(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs" / "telemetry"
    hand_path = logs_root / "PokerTH" / "sessions" / "run_1" / "hands" / "hand_1.jsonl"
    hand_path.parent.mkdir(parents=True)
    hand_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "ml_decision_snapshot",
                        "snapshot_id": "PokerTH:1:1",
                        "metadata": {"street": "PREFLOP"},
                        "features": {
                            "hero_cards": ["Ah", "Kd"],
                            "board_cards": [],
                            "hero_position": "BTN",
                            "pot": 150.0,
                            "to_call": 100.0,
                            "ev": 50.0,
                            "call_max": 300.0,
                            "buttons": [{"enabled": True, "state": "paie", "value": 100.0}],
                            "players": [{"stack": 2500.0, "stack_start": 3000.0}],
                        },
                        "labels": {
                            "legacy_action": "RAISE",
                            "legacy_raise_amount": 300.0,
                            "known_bug_risk": False,
                        },
                        "quality_flags": {
                            "hero_cards_uncertain": False,
                            "board_uncertain": False,
                            "opponent_count_uncertain": False,
                            "pot_to_call_incoherent": False,
                            "buttons_incoherent": False,
                            "street_transient": False,
                            "usable_for_training": True,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "ml_decision_snapshot",
                        "snapshot_id": "PokerTH:1:2",
                        "metadata": {"street": "PREFLOP"},
                        "features": {"pot": 150.0, "to_call": 100.0},
                        "labels": {"legacy_action": "WAIT", "known_bug_risk": False},
                        "quality_flags": {"usable_for_training": True},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = rebuild_export(logs_root=logs_root, output_dir=tmp_path / "dist" / "ml_dataset_export")
    rows = [
        json.loads(line)
        for line in (tmp_path / "dist" / "ml_dataset_export" / "training_dataset.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["snapshots_read"] == 2
    assert summary["training_rows"] == 1
    assert rows[0]["features"]["amount_unit_value"] == 100.0
    assert rows[0]["features"]["pot_bb"] == 1.5
    assert rows[0]["features"]["to_call_bb"] == 1.0
    assert rows[0]["features"]["buttons"][0]["value_bb"] == 1.0
    assert rows[0]["features"]["players"][0]["stack_bb"] == 25.0
    assert rows[0]["labels"]["legacy_raise_amount_bb"] == 3.0
