"""Whisper 래퍼 — imageio-ffmpeg 정적 바이너리를 PATH에 주입해 sudo 없이 동작."""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FFMPEG_PATH_INJECTED = False
_MODEL_CACHE: dict[str, Any] = {}


def _ensure_ffmpeg_on_path() -> None:
    """imageio-ffmpeg 바이너리를 Whisper 가 찾을 수 있는 `ffmpeg` 이름으로 PATH 에 노출.

    imageio-ffmpeg 배포 바이너리는 `ffmpeg-linux-x86_64-vX.Y.Z` 처럼 버전 접미사가 붙어 있어
    Whisper 의 `subprocess.run(["ffmpeg", ...])` 가 PATH 룩업에 실패한다. 임시 디렉토리에
    `ffmpeg` 이름의 심볼릭 링크를 만들어 그 디렉토리를 PATH 앞에 prepend.
    """
    global _FFMPEG_PATH_INJECTED
    if _FFMPEG_PATH_INJECTED:
        return
    try:
        import imageio_ffmpeg  # noqa: WPS433 (런타임 import)

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        shim_dir = Path(tempfile.gettempdir()) / "voice-notes-ffmpeg"
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim_path = shim_dir / "ffmpeg"

        # 기존 링크가 있고 대상이 바뀌었으면 갱신
        needs_link = True
        if shim_path.is_symlink():
            try:
                if os.readlink(shim_path) == ffmpeg_exe:
                    needs_link = False
                else:
                    shim_path.unlink()
            except OSError:
                shim_path.unlink(missing_ok=True)
        elif shim_path.exists():
            shim_path.unlink()

        if needs_link:
            os.symlink(ffmpeg_exe, shim_path)

        current_path = os.environ.get("PATH", "")
        parts = current_path.split(os.pathsep) if current_path else []
        shim_dir_str = str(shim_dir)
        if shim_dir_str not in parts:
            os.environ["PATH"] = os.pathsep.join([shim_dir_str] + parts)
        logger.info("ffmpeg shim 준비: %s → %s", shim_path, ffmpeg_exe)
    except Exception:
        logger.exception("imageio-ffmpeg 경로 주입 실패 — 시스템 ffmpeg 에 의존합니다")
    _FFMPEG_PATH_INJECTED = True


@dataclass
class TranscriptSegment:
    start: float     # seconds
    end: float       # seconds
    text: str


@dataclass
class TranscriptResult:
    language: str | None         # whisper 가 감지한 언어 코드 (ko/en/...)
    duration_seconds: float      # 마지막 세그먼트 end (없으면 0)
    text: str                    # 전체 이어붙인 본문
    segments: list[TranscriptSegment]
    model: str


class Transcriber:
    """Whisper 모델 래퍼. 모델은 프로세스 수명동안 lazy-load 후 캐시."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        _ensure_ffmpeg_on_path()

    def _load_model(self):
        if self._model_name in _MODEL_CACHE:
            return _MODEL_CACHE[self._model_name]
        import whisper  # noqa: WPS433

        logger.info("Whisper 모델 로드 시작: %s (CPU)", self._model_name)
        t0 = time.monotonic()
        model = whisper.load_model(self._model_name)
        logger.info(
            "Whisper 모델 로드 완료: %s (%.1fs)",
            self._model_name,
            time.monotonic() - t0,
        )
        _MODEL_CACHE[self._model_name] = model
        return model

    def transcribe(self, audio_path: Path, language: str | None) -> TranscriptResult:
        """오디오 파일을 전사. language=None 이면 자동 감지."""
        model = self._load_model()

        kwargs: dict[str, Any] = {
            "verbose": False,
            "fp16": False,  # CPU 환경
        }
        if language:
            kwargs["language"] = language

        logger.info(
            "전사 시작: %s (language=%s)", audio_path.name, language or "auto"
        )
        t0 = time.monotonic()
        result = model.transcribe(str(audio_path), **kwargs)
        elapsed = time.monotonic() - t0
        logger.info("전사 완료: %s (%.1fs)", audio_path.name, elapsed)

        raw_segments = result.get("segments") or []
        segments = [
            TranscriptSegment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text=str(s.get("text", "")).strip(),
            )
            for s in raw_segments
        ]
        duration = segments[-1].end if segments else 0.0
        text = (result.get("text") or "").strip()
        language_detected = result.get("language") or language

        return TranscriptResult(
            language=language_detected,
            duration_seconds=duration,
            text=text,
            segments=segments,
            model=self._model_name,
        )


def format_timestamp(seconds: float) -> str:
    """transcript.txt 타임라인용 [hh:mm:ss] 포맷."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_transcript_file(
    result: TranscriptResult,
    *,
    source_filename: str,
    created_at_iso: str,
) -> str:
    """transcript.txt 본문 전체를 문자열로 렌더링."""
    header_lines = [
        f"# 전사본: {source_filename}",
        f"- 생성 시각: {created_at_iso}",
        f"- 길이: {format_timestamp(result.duration_seconds)}",
        f"- 언어: {result.language or 'unknown'}",
        f"- 모델: {result.model}",
        "",
        "---",
        "",
    ]

    body_lines: list[str] = []
    if result.segments:
        for seg in result.segments:
            body_lines.append(
                f"[{format_timestamp(seg.start)} → {format_timestamp(seg.end)}] "
                f"{seg.text}"
            )
    else:
        body_lines.append(result.text or "(빈 전사 결과)")

    body_lines.append("")
    body_lines.append("---")
    body_lines.append("")
    body_lines.append("## 전체 텍스트")
    body_lines.append("")
    body_lines.append(result.text or "")

    return "\n".join(header_lines + body_lines) + "\n"
