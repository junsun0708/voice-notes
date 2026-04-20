"""storage.py — 경로 구성/메타 파일 단위 테스트."""
from __future__ import annotations

from pathlib import Path

from src.storage import (
    build_paths,
    ensure_dir,
    format_duration,
    read_meta,
    write_meta,
)


def test_build_paths_uses_file_id_and_ext(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "FABC123", "m4a")
    assert paths.root.parent.parent == tmp_path
    assert paths.root.name == "FABC123"
    assert paths.original.name == "original.m4a"
    assert paths.transcript.name == "transcript.txt"
    assert paths.detailed.name == "detailed.md"
    assert paths.summary.name == "summary.md"
    assert paths.meta.name == "meta.json"


def test_build_paths_strips_leading_dot(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "F1", ".webm")
    assert paths.original.name == "original.webm"


def test_build_paths_defaults_to_bin_when_no_ext(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "F1", "")
    assert paths.original.name == "original.bin"


def test_exists_complete_requires_three_files(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "F1", "m4a")
    ensure_dir(paths.root)
    assert paths.exists_complete() is False
    paths.transcript.write_text("t", encoding="utf-8")
    paths.detailed.write_text("d", encoding="utf-8")
    assert paths.exists_complete() is False
    paths.summary.write_text("s", encoding="utf-8")
    assert paths.exists_complete() is True


def test_write_and_read_meta_roundtrip(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "F1", "m4a")
    data = {"file_id": "F1", "language": "ko", "duration_seconds": 12.5}
    write_meta(paths.meta, data)
    loaded = read_meta(paths.meta)
    assert loaded == data


def test_read_meta_returns_none_for_missing(tmp_path: Path) -> None:
    assert read_meta(tmp_path / "nope.json") is None


def test_format_duration() -> None:
    assert format_duration(None) == "unknown"
    assert format_duration(0) == "unknown"
    assert format_duration(59) == "0:59"
    assert format_duration(60) == "1:00"
    assert format_duration(3599) == "59:59"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3661) == "1:01:01"
