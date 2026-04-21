"""processor.py — 원본 이동(processed/failed) 헬퍼 단위 테스트.

실제 Whisper/Claude 호출 파이프라인은 외부 리소스 의존이라 여기서는 다루지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.processor import move_to_failed, move_to_processed


def _make_config(tmp_path: Path, *, processed: Path | None) -> Config:
    return Config(
        inbox_dir=tmp_path / "inbox",
        output_dir=tmp_path / "outputs",
        processing_dir=tmp_path / "processing",
        processed_dir=processed,
        failed_dir=tmp_path / "failed",
    )


def test_move_to_processed_moves_file(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, processed=tmp_path / "processed")
    src = tmp_path / "a.m4a"
    src.write_bytes(b"audio")

    moved = move_to_processed(src, config=cfg)
    assert moved is not None
    assert moved.is_file()
    assert not src.exists()
    # processed/<YYYY-MM-DD>/a.m4a
    assert moved.parent.parent == tmp_path / "processed"
    assert moved.name == "a.m4a"


def test_move_to_processed_with_none_deletes(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, processed=None)
    src = tmp_path / "a.m4a"
    src.write_bytes(b"audio")

    result = move_to_processed(src, config=cfg)
    assert result is None
    assert not src.exists()


def test_move_to_processed_dedupes_same_name(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, processed=tmp_path / "processed")
    src1 = tmp_path / "a.m4a"
    src1.write_bytes(b"1")
    first = move_to_processed(src1, config=cfg)
    assert first is not None

    src2 = tmp_path / "a.m4a"
    src2.write_bytes(b"2")
    second = move_to_processed(src2, config=cfg)
    assert second is not None
    assert first != second
    assert first.is_file() and second.is_file()


def test_move_to_failed_writes_error_log(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, processed=tmp_path / "processed")
    src = tmp_path / "broken.m4a"
    src.write_bytes(b"bad")

    moved = move_to_failed(src, config=cfg, reason="Whisper 전사 실패: ...")
    assert moved is not None
    assert moved.is_file()
    log = moved.parent / f"{moved.name}.error.log"
    assert log.is_file()
    assert "전사 실패" in log.read_text(encoding="utf-8")


def test_move_to_failed_returns_none_when_missing(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, processed=None)
    missing = tmp_path / "nope.m4a"
    assert move_to_failed(missing, config=cfg, reason="x") is None
