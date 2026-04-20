# voice-notes

안드로이드(또는 어느 클라이언트든) Slack 채널에 올린 음성 녹음 파일을 감지해
**Whisper large-v3 로 전사 → Claude CLI 로 상세/요약 생성 → 스레드에 3종 파일 첨부**
하는 Slack 봇.

## 파이프라인

```
Slack 오디오 파일 공유 (message.file_share + mimetype audio/*)
  ↓ 파일 다운로드 (Bot 토큰)
  ↓ Whisper large-v3 (로컬 CPU, imageio-ffmpeg 정적 바이너리 사용)
  ↓ Claude CLI 구독 인증 (claude -p subprocess, 순차 호출)
      1. detailed.md  (상세 정리)
      2. summary.md   (요약)
  ↓ outputs/<YYYY-MM-DD>/<file_id>/ 에 저장
  ↓ Slack 스레드 답글: 요약 본문 inline + 3개 파일 업로드
```

저장 구조:

```
outputs/<YYYY-MM-DD>/<slack-file-id>/
  original.<ext>     # 원본 오디오
  transcript.txt     # Whisper 타임스탬프 세그먼트 + 전체 텍스트
  detailed.md        # Claude 상세 정리
  summary.md         # Claude 요약
  meta.json          # file_id, channel, user, duration, model, language, ...
```

## 인증 / 런타임

- **Claude**: Claude Code CLI 구독 인증(OAuth) 을 그대로 재사용합니다. `claude login` 만 되어 있으면
  `ANTHROPIC_API_KEY` 불필요. `claude` 가 PATH 에 있어야 합니다.
- **Slack**: Socket Mode 로 이벤트를 수신합니다(외부 공개 HTTP 엔드포인트 불필요).

## 설치

```bash
cd /home/jyh/a-projects/voice-notes
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Whisper `large-v3` 모델(~1.5GB)** 은 이 설치 단계에서는 내려받지 않습니다. 첫 실제
> 전사 호출 시 자동 다운로드되어 `~/.cache/whisper/` 에 저장됩니다.

## Slack 앱 설정 (Socket Mode, 한국어)

1. <https://api.slack.com/apps> → **Create New App** → *From scratch* (또는 기존 trend-bot/daily-brief-bot 앱 재사용).
2. 좌측 **Socket Mode** 메뉴 → **Enable Socket Mode** 를 켠다.
3. 처음 켜면 App-Level Token 발급 화면이 뜬다. 이름: `voice-notes-socket`, 스코프: `connections:write`.
   발급된 토큰(`xapp-...`) 을 `.env` 의 `SLACK_APP_TOKEN` 에 넣는다.
4. **OAuth & Permissions** → *Bot Token Scopes* 에 다음을 추가:
   - `channels:history` (퍼블릭 채널 이벤트 수신)
   - `groups:history` (프라이빗 채널이면 필요)
   - `files:read` (업로드된 파일 메타/다운로드 URL)
   - `files:write` (결과 파일 업로드)
   - `chat:write` (스레드 답글)
   - `chat:write.public` (참여하지 않은 공개 채널에도 쓰기 필요 시)
5. **Event Subscriptions** → *Enable Events* 를 켜고, *Subscribe to bot events* 에서
   `message.channels` (또는 프라이빗이면 `message.groups`) 를 추가.
   Socket Mode 를 쓰므로 **Request URL 은 입력하지 않는다.**
6. **Install App** 또는 **Reinstall** → 봇을 워크스페이스에 설치하고 `xoxb-...` 를 `.env` 의 `SLACK_BOT_TOKEN` 에.
7. 대상 채널에 봇을 초대(`/invite @voice-notes`), 해당 채널 ID(`C0...`) 를 `SLACK_CHANNEL_ID` 에.

> 이 봇은 `SLACK_CHANNEL_ID` 로 지정된 **단일 채널에서만** 반응합니다. 다른 채널 이벤트는 조용히 무시합니다.

## 환경 변수

```bash
cp .env.example .env
```

| 변수 | 설명 | 기본값 |
|------|------|-------|
| `SLACK_BOT_TOKEN` | Bot OAuth 토큰 (`xoxb-...`) | - |
| `SLACK_APP_TOKEN` | Socket Mode 용 App-Level 토큰 (`xapp-...`) | - |
| `SLACK_CHANNEL_ID` | 대상 채널 ID (`C0...`) | - |
| `WHISPER_MODEL` | Whisper 모델명 | `large-v3` |
| `WHISPER_LANGUAGE` | 언어 코드. `auto` 면 자동 감지. | `auto` |
| `ANTHROPIC_MODEL` | Claude CLI `--model` 값 | `sonnet` |
| `OUTPUT_DIR` | 결과 저장 디렉토리 (상대 경로면 프로젝트 루트 기준) | `outputs` |

## 실행

```bash
source .venv/bin/activate

# 상시 Socket Mode 리스너
python -m src.main

# 혹은 nohup / systemd 용 스크립트
bash scripts/run.sh
```

운영 권장 방식: `tmux` 세션 + `scripts/run.sh`, 또는 systemd user service.

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
  15~20분 정도 걸립니다. 봇은 처리 시작 시 즉시 스레드에 "전사 시작" 안내를 올립니다.
- 더 빠르게 돌리려면 `WHISPER_MODEL=medium` 또는 `small` 로 낮추세요.

## 에러 처리

각 단계(다운로드 / 전사 / 분석)는 독립적으로 감싸져 있으며, 실패 시 스레드 답글 메시지가
어느 단계에서 멎었는지 업데이트됩니다. 같은 `file_id` 가 중복 수신되어도 `outputs/` 에
결과가 이미 있으면 스킵합니다 (idempotent).

## 주요 파일

- `src/main.py` — Socket Mode 리스너 + 파이프라인 오케스트레이션
- `src/config.py` — 환경변수 로딩
- `src/slack_io.py` — 파일 다운로드 + 스레드 업데이트 + `files_upload_v2`
- `src/transcriber.py` — Whisper 래퍼, ffmpeg PATH 주입
- `src/analyzer.py` — `claude -p` subprocess (trend-bot 패턴 재사용)
- `src/storage.py` — outputs 경로, meta.json
- `scripts/run.sh` — 상시 구동 래퍼
