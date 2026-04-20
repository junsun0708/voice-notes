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
    slack_bot_token: str
    slack_app_token: str
    slack_channel_id: str

    whisper_model: str = "large-v3"
    # "auto" 면 자동 감지. 그 외에는 ISO 639-1 코드 (ko, en, ja...).
    whisper_language: str = "auto"

    # Claude CLI 구독 인증 사용. api_key 불필요.
    anthropic_model: str = "sonnet"

    output_dir: Path = PROJECT_ROOT / "outputs"

    @property
    def whisper_language_or_none(self) -> str | None:
        """Whisper `transcribe(language=...)` 에 넘길 값. auto → None."""
        lang = (self.whisper_language or "").strip().lower()
        if not lang or lang == "auto":
            return None
        return lang


def load_config() -> Config:
    env_file = _find_env_file()
    if env_file:
        load_dotenv(env_file)

    slack_bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    slack_app_token = os.environ.get("SLACK_APP_TOKEN", "").strip()
    slack_channel_id = os.environ.get("SLACK_CHANNEL_ID", "").strip()

    missing: list[str] = []
    if not slack_bot_token:
        missing.append("SLACK_BOT_TOKEN")
    if not slack_app_token:
        missing.append("SLACK_APP_TOKEN")
    if not slack_channel_id:
        missing.append("SLACK_CHANNEL_ID")

    if missing:
        raise EnvironmentError(
            f"필수 환경 변수 누락: {', '.join(missing)}. "
            f".env.example 을 .env 로 복사해 값을 채워 주세요."
        )

    output_dir_raw = os.environ.get("OUTPUT_DIR", "").strip() or "outputs"
    output_path = Path(output_dir_raw)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    return Config(
        slack_bot_token=slack_bot_token,
        slack_app_token=slack_app_token,
        slack_channel_id=slack_channel_id,
        whisper_model=os.environ.get("WHISPER_MODEL", "large-v3").strip() or "large-v3",
        whisper_language=os.environ.get("WHISPER_LANGUAGE", "auto").strip() or "auto",
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "sonnet").strip() or "sonnet",
        output_dir=output_path,
    )


# Claude CLI timeout (상세/요약 각각). large-v3 전사 텍스트가 길 수 있으므로 넉넉히.
CLAUDE_TIMEOUT_SECONDS = 600
