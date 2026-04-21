# voice-notes

로컬 폴더에 오디오 파일을 떨어뜨리면 **Whisper large-v3 로 전사 → Claude CLI 로 상세/요약 생성**
해서 날짜/시간별 폴더에 저장해주는 개인용 음성 노트 도구.

Slack 봇 구성 없이, **파일 드롭만으로 동작**합니다.

## 파이프라인

```
inbox/audio.m4a  (파일 드롭)
  ↓ watchdog 감지 → processing/ 으로 이동
  ↓ Whisper large-v3 전사 (로컬 CPU)
  ↓ Claude CLI 구독 인증 (claude -p subprocess, 순차 호출)
      1. detailed.md  (상세 정리)
      2. summary.md   (요약)
  ↓ outputs/<YYYY-MM-DD>/<HHMMSS-slug>/ 에 저장
  ↓ 원본은 processed/<YYYY-MM-DD>/ 로 이동 (또는 삭제)
```

저장 구조:

```
outputs/<YYYY-MM-DD>/<HHMMSS-슬러그>/
  original.<ext>     # 원본 오디오 (복사본)
  transcript.txt     # Whisper 타임스탬프 세그먼트 + 전체 텍스트
  detailed.md        # Claude 상세 정리 (개요·결정사항·액션·미해결 질문)
  summary.md         # Claude 요약 (tl;dr + 핵심 요약 + 주요 포인트)
  meta.json          # source_filename, duration, model, language, ...
```

## 인증 / 런타임

- **Claude**: Claude Code CLI 구독 인증(OAuth) 을 그대로 재사용합니다. `claude login` 만
  되어 있으면 `ANTHROPIC_API_KEY` 불필요. `claude` 가 PATH 에 있어야 합니다.
- **Whisper**: CPU 로컬 추론. `large-v3` 모델은 첫 실제 전사 호출 시 자동 다운로드
  되어 `~/.cache/whisper/` 에 저장됩니다(~1.5GB).

## 설치

```bash
cd /home/jyh/a-projects/voice-notes
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 환경 변수

```bash
cp .env.example .env
```

| 변수 | 설명 | 기본값 |
|------|------|-------|
| `INBOX_DIR` | 감시할 폴더. 여기에 오디오 파일을 드롭. | `inbox` |
| `OUTPUT_DIR` | 결과 저장 루트. | `outputs` |
| `PROCESSING_DIR` | 처리 중 임시 스테이징 폴더. | `processing` |
| `PROCESSED_DIR` | 처리 완료 원본 보관 폴더. `none` 으로 두면 처리 후 삭제. | `processed` |
| `FAILED_DIR` | 처리 실패 원본 + `.error.log` 보관. | `failed` |
| `WHISPER_MODEL` | Whisper 모델명 (`tiny`/`base`/`small`/`medium`/`large-v3`). | `large-v3` |
| `WHISPER_LANGUAGE` | 언어 코드. `auto` 면 자동 감지. | `auto` |
| `ANTHROPIC_MODEL` | Claude CLI `--model` 값. | `sonnet` |

상대 경로는 프로젝트 루트(`voice-notes/`) 기준으로 해석됩니다.

## 실행

### 상시 watch 모드

```bash
source .venv/bin/activate
python -m src.main
```

`inbox/` 에 오디오 파일이 생기면 자동으로 처리합니다. `Ctrl+C` 로 종료.

운영 권장: `tmux` 세션 + `scripts/run.sh`, 또는 systemd user service.

### 단일 파일 1회 처리 (원본 이동 없음)

```bash
python -m src.main --file /path/to/recording.m4a
```

스크립트·cron·수동 실행에 적합. 원본 파일은 그대로 두고 `outputs/` 에만 결과가 쌓입니다.

### inbox 에 이미 있는 파일만 한 번 처리

```bash
python -m src.main --once
```

`inbox/` 안의 파일을 모두 처리한 뒤 종료 (watch 상주하지 않음).

## 지원 포맷

`mp3`, `m4a`, `wav`, `flac`, `ogg`, `opus`, `webm`, `mp4`, `mpga`, `mpeg`, `aac`

그 외 확장자는 무시됩니다. 필요 시 `src/config.py` 의 `AUDIO_EXTENSIONS` 에 추가.

## Docker (참고)

`docker-compose.yml` / `Dockerfile` 은 참고용입니다. 구독 인증(`claude login`) 크리덴셜이
호스트 사용자 디렉토리에 저장되므로 **호스트에서 그대로 실행하는 방식이 가장 단순**합니다.

## 테스트

```bash
source .venv/bin/activate
pip install pytest
python -m pytest tests/ -v
```

## 성능 안내

- Whisper `large-v3` + CPU 는 **실시간 배수 약 0.5x ~ 0.7x** 수준으로, 30분 오디오에
  15~20분 정도 걸립니다.
- 더 빠르게 돌리려면 `WHISPER_MODEL=medium` 또는 `small` 로 낮추세요.
- 처리는 **단일 워커 스레드로 직렬화**됩니다 (CPU 경합 방지). inbox 에 여러 파일을
  동시에 던져도 큐에 쌓여 순차 처리됩니다.

## 에러 처리

- 파이프라인이 실패하면 해당 원본은 `failed/` 로 이동하고 `<파일명>.error.log` 가
  함께 저장됩니다.
- 복구 방법: 원인을 제거한 뒤 `failed/` 의 파일을 `inbox/` 로 다시 옮기면 재처리됩니다.

## 주요 파일

- `src/main.py` — argparse 엔트리 (watch / --file / --once)
- `src/config.py` — 환경변수 로딩, 지원 확장자 목록
- `src/watcher.py` — watchdog 기반 inbox 감시 + 파일 안정화 대기
- `src/processor.py` — 단일 파일 처리 파이프라인, processed/failed 이동
- `src/transcriber.py` — Whisper 래퍼, ffmpeg PATH 주입
- `src/analyzer.py` — `claude -p` subprocess 호출
- `src/storage.py` — 결과 경로 구성, meta.json
- `scripts/run.sh` — 상시 구동 래퍼
