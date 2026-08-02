"""prompt_toolkit 输入会话测试。"""

import asyncio
from pathlib import Path

import pytest
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from chatbot_rag.cli.input_session import PromptInputSession, ReplyInterrupt


def test_prompt_session_uses_thin_beam_cursor(tmp_path: Path) -> None:
    """输入态应使用细竖线光标，避免终端默认的粗块光标。"""
    session = PromptInputSession(
        tmp_path / "history",
        terminal_output=DummyOutput(),
    )

    assert session._session.cursor is CursorShape.BEAM


def test_prompt_message_shows_reply_activity(tmp_path: Path) -> None:
    """输入提示应展示回复活动状态，并在空闲时移除。"""
    session = PromptInputSession(
        tmp_path / "history",
        terminal_output=DummyOutput(),
    )

    session.update_activity("正在思考...")
    prompt_text = "".join(
        fragment for _, fragment in session._prompt_message()
    )
    assert "正在思考..." in prompt_text

    session.update_activity(None)
    prompt_text = "".join(
        fragment for _, fragment in session._prompt_message()
    )
    assert "正在思考" not in prompt_text


@pytest.mark.asyncio
async def test_prompt_session_submits_multiline_input(tmp_path: Path) -> None:
    """Esc+Enter 应插入换行，Enter 应提交完整消息。"""
    with create_pipe_input() as pipe_input:
        session = PromptInputSession(
            tmp_path / "history",
            terminal_input=pipe_input,
            terminal_output=DummyOutput(),
        )
        read_task = asyncio.create_task(session.read())
        await asyncio.sleep(0)
        session.update_status(queue_size=2)

        pipe_input.send_text("第一行\x1b\r第二行\r")

        assert await asyncio.wait_for(read_task, timeout=1) == "第一行\n第二行"


@pytest.mark.asyncio
async def test_prompt_session_persists_and_recalls_history(
    tmp_path: Path,
) -> None:
    """上一条消息应持久化，并可通过上方向键读取。"""
    history_path = tmp_path / "nested" / "history"
    with create_pipe_input() as pipe_input:
        session = PromptInputSession(
            history_path,
            terminal_input=pipe_input,
            terminal_output=DummyOutput(),
        )

        first_read = asyncio.create_task(session.read())
        await asyncio.sleep(0)
        pipe_input.send_text("历史消息\r")
        assert await asyncio.wait_for(first_read, timeout=1) == "历史消息"

        second_read = asyncio.create_task(session.read())
        await asyncio.sleep(0)
        pipe_input.send_text("\x1b[A\r")
        assert await asyncio.wait_for(second_read, timeout=1) == "历史消息"

    assert history_path.exists()
    assert "历史消息" in history_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_prompt_session_uses_escape_to_request_interrupt(
    tmp_path: Path,
) -> None:
    """独立 Esc 应退出当前输入并产生回复中断信号。"""
    with create_pipe_input() as pipe_input:
        session = PromptInputSession(
            tmp_path / "history",
            terminal_input=pipe_input,
            terminal_output=DummyOutput(),
        )
        read_task = asyncio.create_task(session.read())
        await asyncio.sleep(0)

        pipe_input.send_text("\x1b")

        with pytest.raises(ReplyInterrupt):
            await asyncio.wait_for(read_task, timeout=1)
