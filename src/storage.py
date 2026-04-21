"""출력 저장 경로 + meta.json 관리."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class OutputPaths:
    root: Path                  # outputs/<YYYY-MM-DD>/<HHMMSS-slug>/
    original: Path              # original.<ext>
    transcript: Path            # transcript.txt
    detailed: Path              # detailed.md
    summary: Path               # summary.md
    meta: Path                  # meta.json


def _slugify(name: str) -> str:
    """파일 stem 을 안전한 디렉토리명으로 변환."""
    cleaned = re.sub(r"[^\w가-힣.-]+", "-", name, flags=re.UNICODE).strip("-.")
    return cleaned[:60] or "audio"


def build_paths(
    output_root: Path,
    stem: str,
    original_ext: str,
    *,
    now: datetime | None = None,
) -> OutputPaths:
    """outputs/<YYYY-MM-DD>/<HHMMSS>-<slug>/ 아래 경로 세트를 구성."""
    moment = now or datetime.now(TIMEZONE)
    date_str = moment.strftime("%Y-%m-%d")
    ts_str = moment.strftime("%H%M%S")
    ext = original_ext.lstrip(".").lower() or "bin"
    slug = _slugify(stem)
    root = output_root / date_str / f"{ts_str}-{slug}"
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
