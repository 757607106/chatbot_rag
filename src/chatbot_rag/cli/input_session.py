"""基于 prompt_toolkit 的异步终端输入。"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from chatbot_rag.cli.commands import SlashCommandCompleter

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold ansicyan",
        "prompt-state": "ansibrightblack",
        "continuation": "ansibrightblack",
        "completion-menu.completion": "bg:#111827 #e5e7eb",
        "completion-menu.completion.current": "bg:#0891b2 #ffffff bold",
        "completion-menu.meta.completion": "bg:#1f2937 #9ca3af",
        "completion-menu.meta.completion.current": "bg:#0e7490 #ffffff",
    },
)


class ReplyInterrupt(Exception):
    """用户请求中断当前智能体回复时抛出的终端控制信号。"""


class PromptInputSession:
    """提供多行编辑、持久化历史与命令补全的输入会话。"""

    def __init__(
        self,
        history_path: Path,
        terminal_input: Input | None = None,
        terminal_output: Output | None = None,
    ) -> None:
        """使用指定的历史文件创建输入会话。

        Args:
            history_path: prompt_toolkit 持久化输入记录的文件。
            terminal_input: 可选的输入实现，用于终端适配测试。
            terminal_output: 可选的输出实现，用于终端适配测试。
        """
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(history_path),
            auto_suggest=AutoSuggestFromHistory(),
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            cursor=CursorShape.BEAM,
            enable_history_search=False,
            multiline=True,
            prompt_continuation=self._continuation,
            key_bindings=_create_key_bindings(),
            style=PROMPT_STYLE,
            reserve_space_for_menu=4,
            erase_when_done=True,
            input=terminal_input,
            output=terminal_output,
        )
        # 缩短独立 Esc 与 Esc+Enter 组合键之间的判定等待时间。
        self._session.app.timeoutlen = 0.2
        self._session.app.ttimeoutlen = 0.1
        self._queue_size = 0
        self._activity: str | None = None

    async def read(self) -> str:
        """异步读取一条可包含换行的用户输入。"""
        return cast(
            str,
            await self._session.prompt_async(
                self._prompt_message,
            ),
        )

    def update_status(self, queue_size: int) -> None:
        """更新输入区显示的队列状态。

        Args:
            queue_size: 尚未开始处理的输入数量。
        """
        self._queue_size = queue_size
        if self._session.app.is_running:
            self._session.app.invalidate()

    def update_activity(self, activity: str | None) -> None:
        """更新输入区显示的回复活动状态。

        Args:
            activity: 当前回复活动（如思考、执行工具），空闲时为 ``None``。
        """
        self._activity = activity
        if self._session.app.is_running:
            self._session.app.invalidate()

    @staticmethod
    def default_history_path() -> Path:
        """返回当前用户的默认 CLI 历史文件路径。"""
        return Path.home() / ".chatbot_rag" / "history"

    @staticmethod
    def _continuation(
        width: int,
        line_number: int,
        wrap_count: int,
    ) -> AnyFormattedText:
        """为换行和软换行生成与主提示对齐的前缀。"""
        del line_number, wrap_count
        return [("class:continuation", "·" * max(width - 1, 0) + " ")]

    def _prompt_message(self) -> AnyFormattedText:
        """在输入提示中显示回复活动状态和实际排队的消息数量。"""
        prompt: list[tuple[str, str]] = [
            ("class:prompt", "user"),
        ]
        state_parts: list[str] = []
        if self._activity:
            state_parts.append(self._activity)
        if self._queue_size:
            state_parts.append(f"队列 {self._queue_size}")
        if state_parts:
            prompt.append(
                ("class:prompt-state", f"  [{' · '.join(state_parts)}]"),
            )
        prompt.append(("class:prompt", " › "))
        return prompt


def _create_key_bindings() -> KeyBindings:
    """创建发送和显式换行快捷键。"""
    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event: KeyPressEvent) -> None:
        """按一次 Enter 提交，保证中文输入法确认后的行为直接。"""
        buffer: Buffer = event.current_buffer
        if buffer.complete_state is not None:
            completion = buffer.complete_state.current_completion
            if completion is not None:
                buffer.apply_completion(completion)
                return
        buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _insert_newline(event: KeyPressEvent) -> None:
        """使用 Esc+Enter 在当前消息中插入换行。"""
        event.current_buffer.insert_text("\n")

    @bindings.add("escape")
    def _interrupt_reply(event: KeyPressEvent) -> None:
        """让输入任务通知会话循环中断当前回复。"""
        event.app.exit(exception=ReplyInterrupt())

    return bindings
