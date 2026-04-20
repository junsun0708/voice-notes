"""voice-notes 엔트리포인트.

Slack Socket Mode 로 오디오 파일 공유 이벤트를 수신 → Whisper 전사 → Claude 분석 →
스레드 답글 + 파일 업로드 + 로컬 저장.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.analyzer import Analyzer
from src.config import Config, load_config
from src.slack_io import SlackIO
from src.storage import (
    OutputPaths,
    build_paths,
    ensure_dir,
    format_duration,
    read_meta,
    write_meta,
)
from src.transcriber import Transcriber, render_transcript_file

logger = logging.getLogger("voice-notes")

TIMEZONE = ZoneInfo("Asia/Seoul")

# 이벤트 디듀플리케이션(같은 파일 ID 동시 수신 방지). 프로세스 로컬.
_processing_lock = threading.Lock()
_in_flight: set[str] = set()


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("slack_bolt").setLevel(logging.INFO)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------- 파이프라인 ----------

def _pick_original_ext(file_meta: dict) -> str:
    """Slack file 메타에서 확장자 추정."""
    name = file_meta.get("name") or ""
    if "." in name:
        return name.rsplit(".", 1)[1].lower()
    filetype = file_meta.get("filetype") or ""
    return filetype.lower() or "bin"


def _reserve(file_id: str) -> bool:
    """처리 시작 전에 예약. 이미 처리 중이면 False."""
    with _processing_lock:
        if file_id in _in_flight:
            return False
        _in_flight.add(file_id)
        return True


def _release(file_id: str) -> None:
    with _processing_lock:
        _in_flight.discard(file_id)


def _safe_update(
    slack: SlackIO, ts: str | None, text: str
) -> None:
    if ts:
        slack.update_message(ts, text)


def process_audio_file(
    *,
    config: Config,
    slack: SlackIO,
    transcriber: Transcriber,
    analyzer: Analyzer,
    file_meta: dict,
    channel_id: str,
    user_id: str | None,
    source_msg_ts: str,
) -> None:
    """한 오디오 파일 처리 파이프라인.

    - source_msg_ts: 원본 메시지의 ts (이 ts 를 thread_ts 로 사용).
    """
    file_id = file_meta.get("id") or ""
    filename = file_meta.get("name") or "audio"
    mimetype = file_meta.get("mimetype") or ""
    download_url = file_meta.get("url_private_download") or file_meta.get(
        "url_private"
    )

    if not file_id or not download_url:
        logger.warning("파일 메타 부족 — 스킵 (id=%s)", file_id)
        return

    if not _reserve(file_id):
        logger.info("이미 처리 중 — 스킵 (file_id=%s)", file_id)
        return

    paths: OutputPaths | None = None
    progress_ts: str | None = None

    try:
        ext = _pick_original_ext(file_meta)
        paths = build_paths(config.output_dir, file_id, ext)

        # idempotent: 이미 결과가 있으면 스킵
        if paths.exists_complete():
            existing_meta = read_meta(paths.meta) or {}
            logger.info("이미 처리된 파일 — 스킵: %s", file_id)
            slack.post_thread(
                source_msg_ts,
                f"이 파일은 이미 분석되어 있습니다 (경로: `{paths.root}`).",
            )
            return

        ensure_dir(paths.root)

        # 1) 시작 알림
        progress_ts = slack.post_thread(
            source_msg_ts,
            f"🎙️ 전사 시작: `{filename}` — 모델 `{config.whisper_model}`. "
            f"large-v3 + CPU 는 30분 음성 ~ 15~20분 걸릴 수 있습니다.",
        )

        # 2) 다운로드
        try:
            slack.download_file(download_url, paths.original)
        except Exception as e:
            logger.exception("다운로드 실패")
            _safe_update(
                slack,
                progress_ts,
                f"❌ 다운로드 실패: `{filename}` — {e}",
            )
            return

        # 3) 전사
        _safe_update(
            slack,
            progress_ts,
            f"🔄 전사 중: `{filename}` — 오래 걸릴 수 있습니다…",
        )
        try:
            lang = config.whisper_language_or_none
            result = transcriber.transcribe(paths.original, language=lang)
        except Exception as e:
            logger.exception("전사 실패")
            _safe_update(
                slack,
                progress_ts,
                f"❌ 전사 실패: `{filename}` — {e}",
            )
            return

        created_at = datetime.now(TIMEZONE).isoformat(timespec="seconds")
        transcript_text_full = render_transcript_file(
            result, source_filename=filename, created_at_iso=created_at
        )
        paths.transcript.write_text(transcript_text_full, encoding="utf-8")

        duration_str = format_duration(result.duration_seconds)
        lang_str = result.language or "unknown"

        # 4) Claude 분석 (상세 → 요약 순차)
        _safe_update(
            slack,
            progress_ts,
            f"📝 정리 중: `{filename}` ({duration_str} · {lang_str}) — Claude 분석…",
        )
        try:
            analysis = analyzer.analyze(result.text)
        except Exception as e:
            logger.exception("Claude 분석 실패")
            _safe_update(
                slack,
                progress_ts,
                f"❌ 분석 실패(전사는 저장됨): `{filename}` — {e}\n"
                f"로컬 경로: `{paths.root}`",
            )
            return

        paths.detailed.write_text(analysis.detailed_md, encoding="utf-8")
        paths.summary.write_text(analysis.summary_md, encoding="utf-8")

        # 5) meta.json
        meta = {
            "file_id": file_id,
            "filename": filename,
            "mimetype": mimetype,
            "source_msg_ts": source_msg_ts,
            "channel": channel_id,
            "user": user_id,
            "duration_seconds": round(result.duration_seconds, 2),
            "duration_human": duration_str,
            "language": lang_str,
            "whisper_model": result.model,
            "claude_model": config.anthropic_model,
            "created_at": created_at,
        }
        write_meta(paths.meta, meta)

        # 6) 결과 알림 — 요약 inline 본문 + 파일 3개 업로드
        inline = (
            f"🎙️ 분석 완료 — `{filename}` · {duration_str} · {lang_str}\n\n"
            f"{analysis.summary_md}"
        )
        _safe_update(slack, progress_ts, inline)

        slack.upload_files_to_thread(
            thread_ts=source_msg_ts,
            files=[
                (paths.transcript, "전사본 (transcript.txt)"),
                (paths.detailed, "상세 정리 (detailed.md)"),
                (paths.summary, "요약 (summary.md)"),
            ],
            initial_comment=None,
        )

        logger.info("처리 완료: %s (%s)", filename, paths.root)

    except Exception as e:
        logger.exception("파이프라인 상위 오류")
        _safe_update(
            slack,
            progress_ts,
            f"❌ 예기치 못한 오류: {e}",
        )
    finally:
        _release(file_id)


# ---------- Slack 이벤트 핸들러 ----------

def _spawn_process(
    *,
    config: Config,
    slack: SlackIO,
    transcriber: Transcriber,
    analyzer: Analyzer,
    file_meta: dict,
    channel_id: str,
    user_id: str | None,
    source_msg_ts: str,
) -> None:
    """처리를 별도 스레드로 돌려 Bolt 이벤트 루프가 막히지 않게 한다."""
    t = threading.Thread(
        target=process_audio_file,
        kwargs=dict(
            config=config,
            slack=slack,
            transcriber=transcriber,
            analyzer=analyzer,
            file_meta=file_meta,
            channel_id=channel_id,
            user_id=user_id,
            source_msg_ts=source_msg_ts,
        ),
        name=f"voice-notes-{file_meta.get('id')}",
        daemon=True,
    )
    t.start()


def build_app(
    config: Config,
    slack: SlackIO,
    transcriber: Transcriber,
    analyzer: Analyzer,
) -> App:
    app = App(token=config.slack_bot_token)

    @app.event("message")
    def handle_message_event(event: dict[str, Any], logger: logging.Logger) -> None:  # noqa: ARG001
        """file_share subtype 메시지에서 오디오 파일만 처리.

        `file_shared` 이벤트 대신 `message.file_share` 를 쓰는 이유:
          - 채널(ts 포함), user, 업로드 컨텍스트를 한 번에 받을 수 있음
          - 스레드 답글을 위한 ts 가 곧바로 확보됨
        """
        # 타겟 채널만
        if event.get("channel") != config.slack_channel_id:
            return
        if event.get("subtype") != "file_share":
            return

        files = event.get("files") or []
        if not files:
            return

        source_msg_ts = event.get("ts") or event.get("event_ts")
        user_id = event.get("user")
        channel_id = event.get("channel")

        audio_files = [
            f for f in files if str(f.get("mimetype") or "").startswith("audio/")
        ]
        if not audio_files:
            return

        for fmeta in audio_files:
            _spawn_process(
                config=config,
                slack=slack,
                transcriber=transcriber,
                analyzer=analyzer,
                file_meta=fmeta,
                channel_id=channel_id,
                user_id=user_id,
                source_msg_ts=source_msg_ts,
            )

    return app


# ---------- 엔트리 ----------

def main() -> None:
    verbose = os.environ.get("VERBOSE", "").lower() in ("1", "true", "yes")
    setup_logging(verbose=verbose)

    try:
        config = load_config()
    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(
        "설정 로드 — channel=%s whisper=%s lang=%s claude=%s output=%s",
        config.slack_channel_id,
        config.whisper_model,
        config.whisper_language,
        config.anthropic_model,
        config.output_dir,
    )

    ensure_dir(config.output_dir)

    slack = SlackIO(config)
    if not slack.test_connection():
        logger.error("Slack 연결 실패 — 중단")
        sys.exit(1)

    transcriber = Transcriber(model_name=config.whisper_model)
    analyzer = Analyzer(model=config.anthropic_model)
    if not analyzer.available:
        logger.warning(
            "claude CLI 미발견 — Slack 이벤트는 받지만 분석 단계에서 실패합니다."
        )

    app = build_app(config, slack, transcriber, analyzer)
    handler = SocketModeHandler(app, config.slack_app_token)

    logger.info("Socket Mode 이벤트 리스너 시작")
    handler.start()


if __name__ == "__main__":
    main()
