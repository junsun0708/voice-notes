"""analyzer.py — 프롬프트/커맨드 구성 단위 테스트.

실제 claude CLI 에 의존하지 않도록 build_cmd_for_test 를 사용한다.
"""
from __future__ import annotations

from src.analyzer import (
    DETAILED_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_cmd_for_test,
)


def test_detailed_prompt_mentions_required_sections() -> None:
    """상세 정리 시스템 프롬프트에는 3개 필수 섹션이 명시돼 있어야 한다."""
    assert "결정 사항" in DETAILED_SYSTEM_PROMPT
    assert "액션 아이템" in DETAILED_SYSTEM_PROMPT
    assert "미해결 질문" in DETAILED_SYSTEM_PROMPT


def test_summary_prompt_has_tldr_and_bullets() -> None:
    """요약 프롬프트에는 tl;dr 줄과 불릿 지침이 있어야 한다."""
    assert "tl;dr" in SUMMARY_SYSTEM_PROMPT
    assert "핵심 요약" in SUMMARY_SYSTEM_PROMPT
    assert "주요 포인트" in SUMMARY_SYSTEM_PROMPT


def test_build_cmd_for_test_has_required_flags() -> None:
    """subprocess 커맨드 구성이 trend-bot 패턴과 동일해야 한다."""
    cmd = build_cmd_for_test(
        claude_bin="/usr/bin/claude",
        model="sonnet",
        system_prompt="sys",
    )
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd
    assert "--system-prompt" in cmd
    assert "--output-format" in cmd
    assert "text" in cmd
    assert "--disable-slash-commands" in cmd
    assert "--no-session-persistence" in cmd
    assert "--tools" in cmd
    # --tools "" (빈 문자열)
    tools_idx = cmd.index("--tools")
    assert cmd[tools_idx + 1] == ""
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "sonnet"


def test_system_prompt_flag_carries_value() -> None:
    cmd = build_cmd_for_test(
        claude_bin="/x/claude",
        model="sonnet",
        system_prompt="MY_SYSTEM",
    )
    sp_idx = cmd.index("--system-prompt")
    assert cmd[sp_idx + 1] == "MY_SYSTEM"
