"""voice-notes 엔트리포인트.

로컬 폴더(inbox) 를 감시하거나(기본), 단일 파일을 CLI 로 처리한다.

사용:
    python -m src.main                    # watch 모드 (inbox 감시)
    python -m src.main --file path/to/a.m4a   # 단일 파일 1회 처리
    python -m src.main --once             # inbox 안 기존 파일만 처리하고 종료
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import shutil
import signal
import sys
import threading
from pathlib import Path

from src.analyzer import Analyzer
from src.config import Config, load_config
from src.processor import (
    ProcessResult,
    move_to_failed,
    move_to_processed,
    process_audio_file,
)
from src.storage import ensure_dir
from src.transcriber import Transcriber
from src.watcher import run_watcher, scan_existing

logger = logging.getLogger("voice-notes")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _build_runtime(config: Config) -> tuple[Transcriber, Analyzer]:
    transcriber = Transcriber(model_name=config.whisper_model)
    analyzer = Analyzer(model=config.anthropic_model)
    if not analyzer.available:
        logger.warning(
            "claude CLI 미발견 — 분석 단계에서 실패합니다. `claude login` 상태를 확인하세요."
        )
    return transcriber, analyzer


def _ensure_dirs(config: Config) -> None:
    ensure_dir(config.inbox_dir)
    ensure_dir(config.output_dir)
    ensure_dir(config.processing_dir)
    ensure_dir(config.failed_dir)
    if config.processed_dir is not None:
        ensure_dir(config.processed_dir)


def _move_to_processing(source: Path, processing_dir: Path) -> Path:
    """inbox 에서 발견된 파일을 processing/ 으로 이동.

    처리 중 재진입을 방지하기 위한 스테이징 단계.
    """
    ensure_dir(processing_dir)
    target = processing_dir / source.name
    if target.exists():
        # 같은 이름이 이미 있으면 suffix 추가
        stem, ext = target.stem, target.suffix
        i = 2
        while True:
            candidate = processing_dir / f"{stem}-{i}{ext}"
            if not candidate.exists():
                target = candidate
                break
            i += 1
    shutil.move(str(source), str(target))
    return target


def _process_one(
    audio_path: Path,
    *,
    config: Config,
    transcriber: Transcriber,
    analyzer: Analyzer,
    move_source: bool,
) -> ProcessResult | None:
    """한 파일 처리: (선택적으로) processing 으로 이동 → 파이프라인 → processed/failed.

    move_source=False 이면 원본 위치를 그대로 두고 처리만 한다 (CLI --file 전용).
    """
    staged: Path | None = None
    try:
        if move_source:
            staged = _move_to_processing(audio_path, config.processing_dir)
            target = staged
        else:
            target = audio_path

        result = process_audio_file(
            target,
            config=config,
            transcriber=transcriber,
            analyzer=analyzer,
        )

        if move_source and staged is not None:
            moved = move_to_processed(staged, config=config)
            if moved is not None:
                logger.info("원본 보관: %s", moved)
            else:
                logger.info("원본 삭제 (PROCESSED_DIR=none)")
        return result

    except Exception as e:
        logger.exception("처리 실패: %s", audio_path.name)
        if move_source and staged is not None:
            move_to_failed(staged, config=config, reason=str(e))
        return None


def run_cli_file(
    config: Config,
    transcriber: Transcriber,
    analyzer: Analyzer,
    file_path: Path,
) -> int:
    if not file_path.is_file():
        logger.error("파일을 찾을 수 없습니다: %s", file_path)
        return 1

    result = _process_one(
        file_path,
        config=config,
        transcriber=transcriber,
        analyzer=analyzer,
        move_source=False,
    )
    if result is None:
        return 1

    print()
    print(f"✅ 결과 디렉토리: {result.output_dir}")
    print(f"🎧 길이: {result.duration_seconds:.1f}s · 언어: {result.language}")
    print()
    print("=== 요약 ===")
    print(result.summary_md)
    return 0


def run_watch_mode(
    config: Config,
    transcriber: Transcriber,
    analyzer: Analyzer,
    *,
    once: bool,
) -> int:
    """inbox 감시 루프를 돌면서 단일 워커 스레드가 순차 처리.

    Whisper large-v3 + CPU 는 병렬로 돌릴 수 없으므로 queue 를 통해 직렬화.
    """
    work_queue: queue.Queue[Path] = queue.Queue()
    stop_event = threading.Event()

    def enqueue(path: Path) -> None:
        work_queue.put(path)

    def worker() -> None:
        while not stop_event.is_set():
            try:
                path = work_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                _process_one(
                    path,
                    config=config,
                    transcriber=transcriber,
                    analyzer=analyzer,
                    move_source=True,
                )
            finally:
                work_queue.task_done()

    worker_thread = threading.Thread(target=worker, name="voice-notes-worker", daemon=True)
    worker_thread.start()

    scan_existing(config.inbox_dir, enqueue)

    if once:
        work_queue.join()
        stop_event.set()
        worker_thread.join(timeout=5.0)
        return 0

    def handle_signal(signum: int, _frame: object) -> None:
        logger.info("시그널 %d 수신 — 종료 준비", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        run_watcher(
            config=config,
            on_audio=enqueue,
            stop_event=stop_event,
        )
    finally:
        stop_event.set()
        worker_thread.join(timeout=10.0)

    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="voice-notes",
        description="로컬 오디오 파일을 Whisper 로 전사하고 Claude 로 상세/요약을 생성합니다.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="단일 오디오 파일을 1회 처리하고 종료 (원본 이동 없음).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="inbox 에 이미 있는 파일만 처리하고 종료 (watch 상주하지 않음).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG 레벨 로깅.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    verbose = args.verbose or os.environ.get("VERBOSE", "").lower() in ("1", "true", "yes")
    setup_logging(verbose=verbose)

    try:
        config = load_config()
    except EnvironmentError as e:
        logger.error(str(e))
        return 1

    _ensure_dirs(config)

    logger.info(
        "설정 — inbox=%s output=%s whisper=%s lang=%s claude=%s",
        config.inbox_dir,
        config.output_dir,
        config.whisper_model,
        config.whisper_language,
        config.anthropic_model,
    )

    transcriber, analyzer = _build_runtime(config)

    if args.file is not None:
        return run_cli_file(config, transcriber, analyzer, args.file)

    return run_watch_mode(config, transcriber, analyzer, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
