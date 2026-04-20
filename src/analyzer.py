"""Claude CLI(구독 인증) subprocess 기반 전사 분석기.

trend-bot/src/summarizer.py 의 호출 패턴을 그대로 재사용:
  claude -p
    --system-prompt ...
    --output-format text
    --disable-slash-commands
    --no-session-persistence
    --tools ""
    --model <model>

ANTHROPIC_API_KEY 없이도 `claude login` 된 상태라면 그 구독 인증을 그대로 쓴다.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from src.config import CLAUDE_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


DETAILED_SYSTEM_PROMPT = (
    "너는 한국어 회의/음성 노트를 구조화하는 편집자다. "
    "입력은 Whisper가 만든 전사 원문(한국어 또는 영어 등)이다. "
    "내용을 빠짐없이 이해하되, 읽기 좋은 마크다운 문서로 '상세 정리'를 만든다. "
    "요구사항:\n"
    "1) 최상단에 한 줄 개요(한 문장).\n"
    "2) 주제 → 소주제로 구조화. `##`, `###` 헤더 사용.\n"
    "3) 발언자가 구분 가능하면 표기(예: `화자 A:`), 불확실하면 추정하지 말 것.\n"
    "4) 언급된 고유명사·숫자·날짜·링크는 원문 그대로 보존.\n"
    "5) 맨 아래에 다음 3개 섹션을 반드시 별도로 둔다(없으면 '없음'으로 표기):\n"
    "   - `## 결정 사항`\n"
    "   - `## 액션 아이템` (담당자 추정은 하지 말고, 작업 내용만 불릿)\n"
    "   - `## 미해결 질문`\n"
    "6) 길이는 원문의 20~40% 수준. 원문에 없는 정보 지어내지 말 것.\n"
    "7) 응답은 마크다운 본문만. 서두 인사말, 코드블록 래핑, 메타 설명 금지."
)

SUMMARY_SYSTEM_PROMPT = (
    "너는 한국어 음성 노트 요약 전문가다. "
    "입력은 Whisper가 만든 전사 원문이다. "
    "다음 형식의 마크다운을 만든다(이외의 말·코드블록 래핑 금지):\n"
    "\n"
    "**tl;dr:** <전체 내용을 한 문장으로>\n"
    "\n"
    "## 핵심 요약\n"
    "3~5줄의 줄글 문단 하나. 무엇에 관한 내용인지, 결론/핵심 주장이 무엇인지.\n"
    "\n"
    "## 주요 포인트\n"
    "- (5개 이내의 불릿. 각 불릿은 한 줄)\n"
    "\n"
    "원문에 없는 내용 지어내지 말 것. 고유명사/숫자/날짜는 원문 그대로 보존."
)


@dataclass(frozen=True)
class Analysis:
    detailed_md: str
    summary_md: str


class Analyzer:
    def __init__(self, model: str) -> None:
        self._model = model
        self._claude_bin = shutil.which("claude")
        if not self._claude_bin:
            logger.error(
                "`claude` CLI 실행 파일을 PATH에서 찾을 수 없습니다. "
                "구독 인증 분석을 위해 Claude Code CLI 설치 + `claude login` 이 필요합니다."
            )

    @property
    def available(self) -> bool:
        return bool(self._claude_bin)

    def analyze(self, transcript_text: str) -> Analysis:
        """전사 텍스트로부터 상세(detailed.md)와 요약(summary.md)을 순차 생성.

        실패 시 RuntimeError.
        """
        if not self._claude_bin:
            raise RuntimeError(
                "claude CLI 가 PATH 에 없어 분석을 진행할 수 없습니다."
            )
        if not transcript_text.strip():
            raise RuntimeError("전사 텍스트가 비어 있어 분석할 수 없습니다.")

        user_msg = (
            "아래는 오디오 전사 원문이다. 지시에 따라 결과물만 출력하라.\n\n"
            "=== 전사 원문 시작 ===\n"
            f"{transcript_text.strip()}\n"
            "=== 전사 원문 끝 ==="
        )

        logger.info("Claude 상세 정리 생성 시작 (모델=%s)", self._model)
        detailed = self._call_claude_cli(DETAILED_SYSTEM_PROMPT, user_msg)
        logger.info("Claude 상세 정리 완료 (%d자)", len(detailed))

        logger.info("Claude 요약 생성 시작 (모델=%s)", self._model)
        summary = self._call_claude_cli(SUMMARY_SYSTEM_PROMPT, user_msg)
        logger.info("Claude 요약 완료 (%d자)", len(summary))

        return Analysis(detailed_md=detailed, summary_md=summary)

    def _call_claude_cli(self, system_prompt: str, user_msg: str) -> str:
        """claude -p 를 subprocess 로 호출하고 stdout 반환."""
        cmd = self._build_cmd(system_prompt)
        logger.debug(
            "claude CLI 호출 (모델=%s, user %d자, system %d자)",
            self._model,
            len(user_msg),
            len(system_prompt),
        )
        result = subprocess.run(
            cmd,
            input=user_msg,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI 실패 (rc={result.returncode}): "
                f"{(result.stderr or '').strip()[:500]}"
            )
        return (result.stdout or "").strip()

    def _build_cmd(self, system_prompt: str) -> list[str]:
        """구독 인증 기준 표준 subprocess 커맨드 구성. 테스트용으로 공개."""
        assert self._claude_bin is not None
        return [
            self._claude_bin,
            "-p",
            "--system-prompt",
            system_prompt,
            "--output-format",
            "text",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--tools",
            "",
            "--model",
            self._model,
        ]


def build_cmd_for_test(claude_bin: str, model: str, system_prompt: str) -> list[str]:
    """Analyzer 인스턴스 없이 명령 구성만 검증할 수 있게 하는 헬퍼.

    (테스트에서 실제 claude 바이너리에 의존하지 않기 위함.)
    """
    return [
        claude_bin,
        "-p",
        "--system-prompt",
        system_prompt,
        "--output-format",
        "text",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--tools",
        "",
        "--model",
        model,
    ]
