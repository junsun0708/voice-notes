"""inbox 디렉토리를 감시해 신규 오디오 파일을 자동 처리."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.config import AUDIO_EXTENSIONS, Config

logger = logging.getLogger(__name__)


def _is_audio(path: Path) -> bool:
    return path.suffix.lstrip(".").lower() in AUDIO_EXTENSIONS


def _wait_until_stable(
    path: Path,
    *,
    poll_seconds: float,
    required_checks: int,
    timeout_seconds: float = 300.0,
) -> bool:
    """파일 크기가 required_checks 회 연속 같은 값이면 안정화됐다고 판단."""
    deadline = time.monotonic() + timeout_seconds
    last_size = -1
    stable = 0
    while time.monotonic() < deadline:
        if not path.exists():
            return False
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == last_size and size > 0:
            stable += 1
            if stable >= required_checks:
                return True
        else:
            stable = 0
            last_size = size
        time.sleep(poll_seconds)
    logger.warning("파일 안정화 타임아웃: %s", path)
    return False


class _InboxHandler(FileSystemEventHandler):
    def __init__(
        self,
        *,
        config: Config,
        on_audio: Callable[[Path], None],
    ) -> None:
        self._config = config
        self._on_audio = on_audio
        self._seen: set[str] = set()
        self._seen_lock = threading.Lock()

    # ---- watchdog callbacks ----

    def on_created(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        self._dispatch(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None)
        if dest:
            self._dispatch(Path(dest))

    def on_modified(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        # 일부 환경에서는 create 이벤트가 오지 않고 modified 만 온다.
        if event.is_directory:
            return
        self._dispatch(Path(event.src_path))

    # ---- internal ----

    def _dispatch(self, path: Path) -> None:
        if not _is_audio(path):
            return
        key = str(path.resolve())
        with self._seen_lock:
            if key in self._seen:
                return
            self._seen.add(key)

        logger.info("inbox 이벤트 감지: %s", path.name)
        # 파일 안정화 대기는 별도 스레드에서 (감시 루프 블로킹 방지)
        thread = threading.Thread(
            target=self._handle_path,
            args=(path, key),
            name=f"inbox-{path.name}",
            daemon=True,
        )
        thread.start()

    def _handle_path(self, path: Path, key: str) -> None:
        try:
            stable = _wait_until_stable(
                path,
                poll_seconds=self._config.stable_poll_seconds,
                required_checks=self._config.stable_checks,
            )
            if not stable:
                logger.warning("파일이 안정되지 않음 — 건너뜀: %s", path)
                return
            self._on_audio(path)
        finally:
            # 같은 파일명이 재등장하면 다시 처리할 수 있도록 seen 해제
            with self._seen_lock:
                self._seen.discard(key)


def scan_existing(inbox: Path, on_audio: Callable[[Path], None]) -> None:
    """봇 시작 시 inbox 에 이미 있는 오디오 파일을 순차 처리 트리거."""
    if not inbox.is_dir():
        return
    for entry in sorted(inbox.iterdir()):
        if entry.is_file() and _is_audio(entry):
            logger.info("기존 파일 처리 대기열 추가: %s", entry.name)
            on_audio(entry)


def run_watcher(
    *,
    config: Config,
    on_audio: Callable[[Path], None],
    stop_event: threading.Event,
) -> None:
    """inbox 감시 루프. stop_event 가 set 될 때까지 블로킹."""
    handler = _InboxHandler(config=config, on_audio=on_audio)
    observer = Observer()
    observer.schedule(handler, str(config.inbox_dir), recursive=False)
    observer.start()
    logger.info("inbox 감시 시작: %s", config.inbox_dir)
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=1.0)
    finally:
        observer.stop()
        observer.join(timeout=5.0)
        logger.info("inbox 감시 종료")
