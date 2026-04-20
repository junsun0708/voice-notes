#!/usr/bin/env bash
# voice-notes 상시 구동 스크립트 (Socket Mode 리스너).
# nohup / tmux / systemd 중 원하는 방식으로 이 스크립트를 실행하면 된다.
set -euo pipefail

PROJECT_DIR="/home/jyh/a-projects/voice-notes"
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "${LOG_DIR}"

# claude CLI(nvm) + 시스템 PATH 노출. Claude Code 설치 경로에 맞게 조정.
export PATH="/home/jyh/.nvm/versions/node/v22.22.1/bin:/usr/local/bin:/usr/bin:/bin"

# Whisper 모델 캐시 (기본 ~/.cache/whisper)
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${HOME}/.cache}"

cd "${PROJECT_DIR}"

LOG_FILE="${LOG_DIR}/run-$(date +%Y%m%d-%H%M%S).log"

# 30일 이상 된 로그 정리
find "${LOG_DIR}" -name 'run-*.log' -mtime +30 -delete 2>/dev/null || true

{
  echo "=== $(date '+%F %T %Z') voice-notes 시작 ==="
  exec "${PROJECT_DIR}/.venv/bin/python" -m src.main
} >> "${LOG_FILE}" 2>&1
