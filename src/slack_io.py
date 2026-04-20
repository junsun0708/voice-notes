"""Slack I/O — 파일 다운로드, 메시지 전송/업데이트, 파일 업로드."""
from __future__ import annotations

import logging
from pathlib import Path

import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from src.config import Config
from src.storage import ensure_dir

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 120
_DOWNLOAD_CHUNK = 64 * 1024


class SlackIO:
    """WebClient 래퍼 + 파일 다운로드 유틸."""

    def __init__(self, config: Config) -> None:
        self._client = WebClient(token=config.slack_bot_token)
        self._channel_id = config.slack_channel_id
        self._bot_token = config.slack_bot_token

    @property
    def client(self) -> WebClient:
        return self._client

    @property
    def channel_id(self) -> str:
        return self._channel_id

    # ----- 다운로드 -----

    def download_file(self, url_private_download: str, dest: Path) -> Path:
        """Slack private 파일을 Bot 토큰으로 다운로드."""
        ensure_dir(dest.parent)
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        logger.info("파일 다운로드: %s → %s", url_private_download, dest)
        with requests.get(
            url_private_download,
            headers=headers,
            stream=True,
            timeout=_DOWNLOAD_TIMEOUT,
            allow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                    if chunk:
                        f.write(chunk)
        size = dest.stat().st_size
        logger.info("다운로드 완료: %s (%d bytes)", dest.name, size)
        return dest

    # ----- 메시지 -----

    def post_thread(self, thread_ts: str, text: str) -> str | None:
        """스레드 답글 posting. 성공 시 ts 반환."""
        try:
            resp = self._client.chat_postMessage(
                channel=self._channel_id,
                thread_ts=thread_ts,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            return resp.get("ts")
        except SlackApiError as e:
            logger.error("스레드 메시지 전송 실패: %s", e.response.get("error"))
            return None

    def update_message(self, ts: str, text: str) -> bool:
        """기존 메시지 내용을 교체."""
        try:
            self._client.chat_update(
                channel=self._channel_id,
                ts=ts,
                text=text,
            )
            return True
        except SlackApiError as e:
            logger.warning("메시지 업데이트 실패(ts=%s): %s", ts, e.response.get("error"))
            return False

    # ----- 파일 업로드 -----

    def upload_files_to_thread(
        self,
        thread_ts: str,
        files: list[tuple[Path, str]],
        initial_comment: str | None = None,
    ) -> bool:
        """files: (경로, 표시 제목) 리스트. files_upload_v2 사용.

        slack-sdk 3.x 의 files_upload_v2 는 file_uploads 파라미터를 받아 복수 파일 일괄 업로드.
        """
        if not files:
            return True
        try:
            file_uploads = []
            for path, title in files:
                file_uploads.append(
                    {
                        "file": str(path),
                        "filename": path.name,
                        "title": title,
                    }
                )
            kwargs = dict(
                channel=self._channel_id,
                thread_ts=thread_ts,
                file_uploads=file_uploads,
            )
            if initial_comment:
                kwargs["initial_comment"] = initial_comment
            self._client.files_upload_v2(**kwargs)
            return True
        except SlackApiError as e:
            logger.error("파일 업로드 실패: %s", e.response.get("error"))
            return False
        except Exception:
            logger.exception("파일 업로드 중 예기치 못한 오류")
            return False

    # ----- 상태 체크 -----

    def test_connection(self) -> bool:
        try:
            r = self._client.auth_test()
            logger.info(
                "Slack auth OK — bot=%s team=%s", r.get("user"), r.get("team")
            )
            return True
        except SlackApiError as e:
            logger.error("Slack auth 실패: %s", e.response.get("error"))
            return False
