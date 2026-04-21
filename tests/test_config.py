"""config.py — 환경변수 로딩 단위 테스트."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import AUDIO_EXTENSIONS, PROJECT_ROOT, Config, load_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "INBOX_DIR",
        "OUTPUT_DIR",
        "PROCESSING_DIR",
        "PROCESSED_DIR",
        "FAILED_DIR",
        "WHISPER_MODEL",
        "WHISPER_LANGUAGE",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_use_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    cfg = load_config()
    assert cfg.inbox_dir == PROJECT_ROOT / "inbox"
    assert cfg.output_dir == PROJECT_ROOT / "outputs"
    assert cfg.processing_dir == PROJECT_ROOT / "processing"
    assert cfg.processed_dir == PROJECT_ROOT / "processed"
    assert cfg.failed_dir == PROJECT_ROOT / "failed"
    assert cfg.whisper_model == "large-v3"
    assert cfg.whisper_language == "auto"
    assert cfg.anthropic_model == "sonnet"


def test_processed_dir_none_disables_archival(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROCESSED_DIR", "none")
    cfg = load_config()
    assert cfg.processed_dir is None


def test_absolute_path_overrides_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    abs_inbox = tmp_path / "custom-inbox"
    monkeypatch.setenv("INBOX_DIR", str(abs_inbox))
    cfg = load_config()
    assert cfg.inbox_dir == abs_inbox


def test_whisper_language_or_none() -> None:
    assert Config(
        inbox_dir=Path("/tmp/i"),
        output_dir=Path("/tmp/o"),
        processing_dir=Path("/tmp/p"),
        processed_dir=None,
        failed_dir=Path("/tmp/f"),
        whisper_language="auto",
    ).whisper_language_or_none is None

    assert Config(
        inbox_dir=Path("/tmp/i"),
        output_dir=Path("/tmp/o"),
        processing_dir=Path("/tmp/p"),
        processed_dir=None,
        failed_dir=Path("/tmp/f"),
        whisper_language="ko",
    ).whisper_language_or_none == "ko"


def test_audio_extensions_contains_common_formats() -> None:
    assert "m4a" in AUDIO_EXTENSIONS
    assert "mp3" in AUDIO_EXTENSIONS
    assert "wav" in AUDIO_EXTENSIONS
    assert "webm" in AUDIO_EXTENSIONS
