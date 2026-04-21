"""환경 변수 로딩 및 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _find_env_file() -> Path | None:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        env_path = parent / ".env"
        if env_path.is_file():
            return env_path
    return None


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    inbox_dir: Path
    output_dir: Path
    processing_dir: Path
    processed_dir: Path | None   # None 이면 처리 후 원본 삭제
    failed_dir: Path

    whisper_model: str = "large-v3"
    # "auto" 면 자동 감지. 그 외에는 ISO 639-1 코드 (ko, en, ja...).
    whisper_language: str = "auto"

    # Claude CLI 구독 인증 사용. api_key 불필요.
    anthropic_model: str = "sonnet"

    # 파일 크기 안정화 체크 (watch 모드): 이 간격마다 size 비교, stable_checks 회 연속 같으면 시작.
    stable_poll_seconds: float = 1.0
    stable_checks: int = 3

    @property
    def whisper_language_or_none(self) -> str | None:
        """Whisper `transcribe(language=...)` 에 넘길 값. auto → None."""
        lang = (self.whisper_language or "").strip().lower()
        if not lang or lang == "auto":
            return None
        return lang


def _resolve_dir(raw: str, default: str) -> Path:
    value = (raw or "").strip() or default
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_config() -> Config:
    env_file = _find_env_file()
    if env_file:
        load_dotenv(env_file)

    inbox = _resolve_dir(os.environ.get("INBOX_DIR", ""), "inbox")
    output = _resolve_dir(os.environ.get("OUTPUT_DIR", ""), "outputs")
    processing = _resolve_dir(os.environ.get("PROCESSING_DIR", ""), "processing")
    failed = _resolve_dir(os.environ.get("FAILED_DIR", ""), "failed")

    processed_raw = (os.environ.get("PROCESSED_DIR", "") or "").strip()
    if processed_raw.lower() == "none":
        processed: Path | None = None
    else:
        processed = _resolve_dir(processed_raw, "processed")

    return Config(
        inbox_dir=inbox,
        output_dir=output,
        processing_dir=processing,
        processed_dir=processed,
        failed_dir=failed,
        whisper_model=os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3",
        whisper_language=os.environ.get("WHISPER_LANGUAGE", "auto").strip() or "auto",
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "sonnet").strip() or "sonnet",
    )


# Claude CLI timeout (상세/요약 각각). large-v3 전사 텍스트가 길 수 있으므로 넉넉히.
CLAUDE_TIMEOUT_SECONDS = 600

# 지원 오디오 확장자.
AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {"mp3", "m4a", "wav", "flac", "ogg", "opus", "webm", "mp4", "mpga", "mpeg", "aac"}
)
