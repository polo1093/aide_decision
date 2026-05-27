#!/usr/bin/env python3
"""Rebuild the trainable ML dataset export from telemetry logs."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence


TRAINING_ACTIONS = {"CHECK", "CALL", "FOLD", "RAISE"}
BLOCKING_QUALITY_FLAGS = (
    "hero_cards_uncertain",
    "board_uncertain",
    "opponent_count_uncertain",
    "amount_unit_missing",
    "pot_to_call_incoherent",
    "buttons_incoherent",
    "street_transient",
)


def rebuild_export(
    *,
    logs_root: Path,
    output_dir: Path,
    example_rows: int = 4,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    snapshots_read = 0
    bad_json = 0

    for path in _hand_log_paths(logs_root):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                bad_json += 1
                continue
            if event.get("type") != "ml_decision_snapshot":
                continue
            snapshots_read += 1
            enriched = enrich_amount_features(event)
            if is_trainable_row(enriched):
                rows.append(enriched)

    training_path = output_dir / "training_dataset.jsonl"
    example_path = output_dir / "example_training_dataset.jsonl"
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(training_path, rows)
        _write_jsonl(example_path, rows[: max(0, example_rows)])

    return {
        "logs_root": str(logs_root),
        "output_dir": str(output_dir),
        "snapshots_read": snapshots_read,
        "bad_json": bad_json,
        "training_rows": len(rows),
        "example_rows": min(max(0, example_rows), len(rows)),
        "training_path": str(training_path),
        "example_path": str(example_path),
        "dry_run": dry_run,
    }


def enrich_amount_features(event: dict[str, Any]) -> dict[str, Any]:
    features = _dict(event.setdefault("features", {}))
    labels = _dict(event.setdefault("labels", {}))
    flags = _dict(event.setdefault("quality_flags", {}))
    metadata = _dict(event.get("metadata"))

    amount_context = infer_amount_context(features=features, metadata=metadata)
    unit_value = amount_context["value"]
    features["amount_unit"] = amount_context["unit"]
    features["amount_unit_value"] = unit_value
    features["amount_unit_source"] = amount_context["source"]

    for key in ("pot", "to_call", "ev", "call_max"):
        features[f"{key}_bb"] = amount_in_unit(features.get(key), unit_value)

    for button in _list(features.get("buttons")):
        if isinstance(button, dict):
            button["value_bb"] = amount_in_unit(button.get("value"), unit_value)

    for player in _list(features.get("players")):
        if isinstance(player, dict):
            player["stack_bb"] = amount_in_unit(player.get("stack"), unit_value)
            player["stack_start_bb"] = amount_in_unit(player.get("stack_start"), unit_value)

    labels["legacy_raise_amount_bb"] = amount_in_unit(labels.get("legacy_raise_amount"), unit_value)
    flags["amount_unit_missing"] = unit_value is None
    flags["usable_for_training"] = not any(bool(flags.get(key)) for key in BLOCKING_QUALITY_FLAGS)

    action = str(labels.get("legacy_action") or labels.get("final_action") or "").upper()
    labels["known_bug_risk"] = bool(labels.get("known_bug_risk"))
    exclusion_reason = label_exclusion_reason(action=action, labels=labels, quality_flags=flags)
    labels["label_valid"] = exclusion_reason is None
    labels["label_exclusion_reason"] = exclusion_reason
    return event


def infer_amount_context(*, features: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    existing = number_or_none(features.get("amount_unit_value"))
    if existing is not None and existing > 0:
        return {
            "unit": features.get("amount_unit") or "big_blind",
            "value": existing,
            "source": features.get("amount_unit_source") or "existing",
        }

    street = str(metadata.get("street") or features.get("street") or "").upper()
    to_call = number_or_none(features.get("to_call"))
    pot = number_or_none(features.get("pot"))
    if street == "PREFLOP" and to_call is not None and to_call > 0:
        if str(features.get("hero_position") or "").upper() == "SB" and pot is not None and pot > 0 and pot / to_call <= 4.0:
            return {"unit": "big_blind", "value": to_call * 2.0, "source": "preflop_small_blind_to_call"}
        return {"unit": "big_blind", "value": to_call, "source": "preflop_to_call"}

    button_values = [
        value
        for button in _list(features.get("buttons"))
        for value in [number_or_none(_dict(button).get("value"))]
        if value is not None and value > 0
    ]
    if button_values:
        return {"unit": "big_blind", "value": min(button_values), "source": "button_value"}

    return {"unit": "big_blind", "value": None, "source": None}


def is_trainable_row(event: dict[str, Any]) -> bool:
    labels = _dict(event.get("labels"))
    flags = _dict(event.get("quality_flags"))
    return (
        event.get("type") == "ml_decision_snapshot"
        and labels.get("label_valid") is True
        and labels.get("known_bug_risk") is False
        and flags.get("usable_for_training") is True
        and flags.get("amount_unit_missing") is False
        and labels.get("legacy_action") in TRAINING_ACTIONS
    )


def label_exclusion_reason(*, action: str, labels: dict[str, Any], quality_flags: dict[str, Any]) -> str | None:
    if labels.get("known_bug_risk") is True:
        return "known_bug_risk"
    if action not in TRAINING_ACTIONS:
        return "non_actionable_label"
    for flag in BLOCKING_QUALITY_FLAGS:
        if quality_flags.get(flag):
            return flag
    if quality_flags.get("usable_for_training") is not True:
        return "not_usable_for_training"
    return None


def amount_in_unit(value: Any, unit_value: Any) -> float | None:
    number = number_or_none(value)
    unit = number_or_none(unit_value)
    if number is None or unit is None or unit <= 0:
        return None
    return round(number / unit, 6)


def number_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def commit_and_push(paths: Sequence[Path], *, message: str, push: bool) -> dict[str, Any]:
    run_git(["add", "-f", *[str(path) for path in paths]])
    staged = run_git(["diff", "--cached", "--name-only"], capture=True).stdout.splitlines()
    if not staged:
        return {"committed": False, "pushed": False, "staged": []}
    run_git(["commit", "-m", message])
    if push:
        run_git(["push"])
    return {"committed": True, "pushed": push, "staged": staged}


def run_git(args: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=capture,
        text=True,
    )


def _hand_log_paths(logs_root: Path) -> Iterable[Path]:
    return sorted(path for path in logs_root.glob("**/hands/*.jsonl") if path.is_file())


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild dist/ml_dataset_export from telemetry logs.")
    parser.add_argument("--logs-root", default="logs/telemetry", type=Path)
    parser.add_argument("--output-dir", default="dist/ml_dataset_export", type=Path)
    parser.add_argument("--example-rows", default=4, type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true", help="Commit the generated JSONL files.")
    parser.add_argument("--push", action="store_true", help="Push after committing. Implies --commit.")
    parser.add_argument("--message", default="Regenerate ML dataset export")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.push:
        args.commit = True

    summary = rebuild_export(
        logs_root=args.logs_root,
        output_dir=args.output_dir,
        example_rows=args.example_rows,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.commit:
        if args.dry_run:
            raise SystemExit("--commit cannot be used with --dry-run")
        git_summary = commit_and_push(
            [
                args.output_dir / "training_dataset.jsonl",
                args.output_dir / "example_training_dataset.jsonl",
            ],
            message=args.message,
            push=args.push,
        )
        print(json.dumps(git_summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
