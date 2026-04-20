"""출력 저장 경로 + meta.json 관리."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class OutputPaths:
    root: Path                  # outputs/<YYYY-MM-DD>/<file_id>/
    original: Path              # original.<ext>
    transcript: Path            # transcript.txt
    detailed: Path              # detailed.md
    summary: Path               # summary.md
    meta: Path                  # meta.json

    def exists_complete(self) -> bool:
        """세 결과물이 모두 생성되어 있으면 True (idempotent 체크)."""
        return (
            self.transcript.is_file()
            and self.detailed.is_file()
            and self.summary.is_file()
        )


def build_paths(output_root: Path, file_id: str, original_ext: str) -> OutputPaths:
    """outputs/<YYYY-MM-DD>/<file_id>/ 아래 경로 세트를 구성.

    original_ext는 점을 포함하든 안 하든 모두 허용.
    """
    date_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    ext = original_ext.lstrip(".") or "bin"
    root = output_root / date_str / file_id
    return OutputPaths(
        root=root,
        original=root / f"original.{ext}",
        transcript=root / "transcript.txt",
        detailed=root / "detailed.md",
        summary=root / "summary.md",
        meta=root / "meta.json",
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_meta(meta_path: Path, data: dict) -> None:
    ensure_dir(meta_path.parent)
    meta_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def read_meta(meta_path: Path) -> dict | None:
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("meta.json 파싱 실패: %s", meta_path)
        return None


def format_duration(seconds: float | None) -> str:
    """초 단위 길이를 사람이 읽는 형태(mm:ss 또는 hh:mm:ss)로."""
    if seconds is None or seconds <= 0:
        return "unknown"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"
