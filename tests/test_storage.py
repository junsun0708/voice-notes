"""storage.py — 경로 구성/메타 파일 단위 테스트."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.storage import (
    build_paths,
    ensure_dir,
    format_duration,
    read_meta,
    write_meta,
)

TZ = ZoneInfo("Asia/Seoul")


def _fixed_now() -> datetime:
    return datetime(2026, 4, 21, 14, 30, 15, tzinfo=TZ)


def test_build_paths_uses_date_time_and_slug(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "meeting notes", "m4a", now=_fixed_now())
    assert paths.root.parent == tmp_path / "2026-04-21"
    # HHMMSS-<slug>
    assert paths.root.name.startswith("143015-")
    assert "meeting" in paths.root.name
    assert paths.original.name == "original.m4a"
    assert paths.transcript.name == "transcript.txt"
    assert paths.detailed.name == "detailed.md"
    assert paths.summary.name == "summary.md"
    assert paths.meta.name == "meta.json"


def test_build_paths_strips_leading_dot_and_lowercases(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "clip", ".WEBM", now=_fixed_now())
    assert paths.original.name == "original.webm"


def test_build_paths_defaults_to_bin_when_no_ext(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "clip", "", now=_fixed_now())
    assert paths.original.name == "original.bin"


def test_build_paths_slugifies_unsafe_chars(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "2026/04/21 회의 @금요일", "m4a", now=_fixed_now())
    # 슬래시/특수문자 제거, 한글은 유지
    assert "/" not in paths.root.name
    assert "@" not in paths.root.name
    assert "회의" in paths.root.name


def test_build_paths_slug_falls_back_when_empty(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "@@@", "m4a", now=_fixed_now())
    assert paths.root.name.endswith("-audio")


def test_write_and_read_meta_roundtrip(tmp_path: Path) -> None:
    paths = build_paths(tmp_path, "clip", "m4a", now=_fixed_now())
    data = {"source_filename": "clip.m4a", "language": "ko", "duration_seconds": 12.5}
    write_meta(paths.meta, data)
    loaded = read_meta(paths.meta)
    assert loaded == data


def test_read_meta_returns_none_for_missing(tmp_path: Path) -> None:
    assert read_meta(tmp_path / "nope.json") is None


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c"
    ensure_dir(target)
    ensure_dir(target)
    assert target.is_dir()


def test_format_duration() -> None:
    assert format_duration(None) == "unknown"
    assert format_duration(0) == "unknown"
    assert format_duration(59) == "0:59"
    assert format_duration(60) == "1:00"
    assert format_duration(3599) == "59:59"
    assert format_duration(3600) == "1:00:00"
    assert format_duration(3661) == "1:01:01"
