"""Tests for launcher tool command helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from launch import (
    available_game_names,
    build_capture_frames_args,
    build_identify_cards_args,
    build_quick_setup_args,
    build_validate_cards_args,
    build_zone_editor_args,
    format_command,
    normalise_game_name,
    script_path_for,
)


def test_available_game_names_lists_profiles_with_coordinates(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    (config_root / "PMU").mkdir(parents=True)
    (config_root / "PMU" / "coordinates.json").write_text("{}", encoding="utf-8")
    (config_root / "NoCoords").mkdir()

    assert available_game_names(config_root) == ["PMU"]


def test_available_game_names_falls_back_to_pmu_for_missing_root(tmp_path: Path) -> None:
    assert available_game_names(tmp_path / "missing") == ["PMU"]


def test_script_path_for_resolves_existing_script() -> None:
    assert script_path_for("quick_setup.py").name == "quick_setup.py"


def test_normalise_game_name_rejects_blank_values() -> None:
    with pytest.raises(ValueError):
        normalise_game_name("   ")


def test_build_quick_setup_args_includes_video_and_selected_skip_flags(tmp_path: Path) -> None:
    args = build_quick_setup_args(
        " PMU ",
        config_root=tmp_path / "config",
        video=r"C:\captures\cards video.mp4",
        edit_zones=False,
        extract_frames=True,
        identify_cards=False,
        validate_video=False,
    )

    assert args == [
        "--game",
        "PMU",
        "--config-root",
        str(tmp_path / "config"),
        "--video",
        r"C:\captures\cards video.mp4",
        "--skip-zone-editor",
        "--skip-identify",
        "--skip-capture-validation",
    ]


def test_build_zone_editor_args_runs_only_zone_step(tmp_path: Path) -> None:
    args = build_zone_editor_args("PMU", config_root=tmp_path / "config")

    assert args == [
        "--game",
        "PMU",
        "--config-root",
        str(tmp_path / "config"),
        "--skip-capture",
        "--skip-identify",
        "--skip-capture-validation",
    ]


def test_individual_script_args_use_selected_profile(tmp_path: Path) -> None:
    config_root = tmp_path / "config"
    video = r"C:\captures\cards_video.avi"

    assert build_capture_frames_args("PMU", video, config_root=config_root) == [
        "--game-dir",
        str(config_root / "PMU"),
        "--video",
        video,
    ]
    assert build_identify_cards_args("PMU") == ["--game", "PMU"]
    assert build_validate_cards_args("PMU", video, config_root=config_root) == [
        "--game",
        "PMU",
        "--game-dir",
        str(config_root / "PMU"),
        "--video",
        video,
    ]


def test_format_command_quotes_parts_with_spaces() -> None:
    assert format_command(["python", r"C:\with space\tool.py", "--game", "PMU"]) == (
        'python "C:\\with space\\tool.py" --game PMU'
    )
