"""단일 오디오 파일을 받아 전사/분석/저장까지 수행하는 핵심 파이프라인."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.analyzer import Analyzer
from src.config import Config
from src.storage import (
    OutputPaths,
    build_paths,
    ensure_dir,
    format_duration,
    write_meta,
)
from src.transcriber import Transcriber, render_transcript_file

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ProcessResult:
    output_dir: Path
    summary_md: str
    detailed_md: str
    transcript_preview: str
    duration_seconds: float
    language: str


def process_audio_file(
    audio_path: Path,
    *,
    config: Config,
    transcriber: Transcriber,
    analyzer: Analyzer,
) -> ProcessResult:
    """한 오디오 파일의 전사/분석/저장 파이프라인.

    성공 시 ProcessResult 반환. 어느 단계든 실패하면 예외.
    호출부에서 원본 이동(processed/failed)은 담당하지 않으므로 별도 처리.
    """
    if not audio_path.is_file():
        raise FileNotFoundError(f"오디오 파일 없음: {audio_path}")

    now = datetime.now(TIMEZONE)
    stem = audio_path.stem
    ext = audio_path.suffix.lstrip(".") or "bin"
    paths = build_paths(config.output_dir, stem, ext, now=now)
    ensure_dir(paths.root)

    logger.info("처리 시작: %s → %s", audio_path.name, paths.root)

    # 1) 원본 복사 (아직 inbox 에 있을 수 있으므로 copy; 호출부가 원본 이동 결정)
    shutil.copy2(audio_path, paths.original)

    # 2) 전사
    lang = config.whisper_language_or_none
    logger.info("전사 단계 — language=%s", lang or "auto")
    result = transcriber.transcribe(paths.original, language=lang)

    created_at = now.isoformat(timespec="seconds")
    transcript_text_full = render_transcript_file(
        result, source_filename=audio_path.name, created_at_iso=created_at
    )
    paths.transcript.write_text(transcript_text_full, encoding="utf-8")

    duration_str = format_duration(result.duration_seconds)
    lang_str = result.language or "unknown"
    logger.info("전사 완료 — %s · %s", duration_str, lang_str)

    # 3) Claude 분석 (상세 → 요약)
    logger.info("Claude 분석 단계")
    analysis = analyzer.analyze(result.text)
    paths.detailed.write_text(analysis.detailed_md, encoding="utf-8")
    paths.summary.write_text(analysis.summary_md, encoding="utf-8")

    # 4) meta.json
    meta = {
        "source_filename": audio_path.name,
        "source_path": str(audio_path),
        "output_dir": str(paths.root),
        "duration_seconds": round(result.duration_seconds, 2),
        "duration_human": duration_str,
        "language": lang_str,
        "whisper_model": result.model,
        "claude_model": config.anthropic_model,
        "created_at": created_at,
    }
    write_meta(paths.meta, meta)

    logger.info("처리 완료: %s", paths.root)
    transcript_preview = (result.text or "")[:300]
    return ProcessResult(
        output_dir=paths.root,
        summary_md=analysis.summary_md,
        detailed_md=analysis.detailed_md,
        transcript_preview=transcript_preview,
        duration_seconds=result.duration_seconds,
        language=lang_str,
    )


def move_to_processed(
    source: Path,
    *,
    config: Config,
    now: datetime | None = None,
) -> Path | None:
    """원본을 processed_dir/<YYYY-MM-DD>/ 아래로 이동. processed_dir=None 이면 삭제.

    반환: 이동된 경로(None 이면 삭제됨).
    """
    moment = now or datetime.now(TIMEZONE)
    if config.processed_dir is None:
        try:
            source.unlink(missing_ok=True)
        except Exception:
            logger.exception("원본 삭제 실패: %s", source)
        return None

    target_dir = config.processed_dir / moment.strftime("%Y-%m-%d")
    ensure_dir(target_dir)
    target = target_dir / source.name
    target = _unique_path(target)
    shutil.move(str(source), str(target))
    return target


def move_to_failed(source: Path, *, config: Config, reason: str) -> Path | None:
    """처리 실패한 원본을 failed_dir 로 이동하고 error.log 를 함께 남긴다."""
    if not source.exists():
        return None
    ensure_dir(config.failed_dir)
    target = _unique_path(config.failed_dir / source.name)
    try:
        shutil.move(str(source), str(target))
    except Exception:
        logger.exception("failed 디렉토리 이동 실패: %s", source)
        return None
    try:
        (target.parent / f"{target.name}.error.log").write_text(
            reason, encoding="utf-8"
        )
    except Exception:
        logger.exception("error.log 기록 실패: %s", target)
    return target


def _unique_path(path: Path) -> Path:
    """동일 이름이 존재하면 `-2`, `-3` ... suffix 를 stem 뒤에 붙인다."""
    if not path.exists():
        return path
    stem = path.stem
    ext = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem}-{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1
