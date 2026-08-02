"""终端斜杠命令及补全。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from prompt_toolkit.completion import Completer, CompleteEvent, Completion
from prompt_toolkit.document import Document


@dataclass(frozen=True, slots=True)
class SlashCommand:
    """一条由终端层处理的本地命令。"""

    name: str
    description: str


COMMANDS = (
    SlashCommand("/help", "显示命令和快捷键"),
    SlashCommand("/clear", "清空终端内容"),
    SlashCommand("/verbose", "切换完整工具输出"),
    SlashCommand("/exit", "退出聊天"),
)


# prompt_toolkit 未发布可被当前 mypy 配置解析的完整类型信息。
class SlashCommandCompleter(Completer):  # type: ignore[misc]
    """仅在当前输入以斜杠开头时补全本地命令。"""

    def get_completions(
        self,
        document: Document,
        complete_event: CompleteEvent,
    ) -> Iterator[Completion]:
        """返回与光标前文本匹配的命令候选。"""
        del complete_event
        text = document.text_before_cursor
        if not text.startswith("/") or any(
            character.isspace() for character in text
        ):
            return

        for command in COMMANDS:
            if command.name.startswith(text):
                yield Completion(
                    command.name,
                    start_position=-len(text),
                    display=command.name,
                    display_meta=command.description,
                )
