"""CLI 本地命令补全测试。"""

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from chatbot_rag.cli.commands import SlashCommandCompleter


def test_completer_suggests_matching_slash_commands() -> None:
    """斜杠前缀应返回匹配命令及说明。"""
    completions = list(
        SlashCommandCompleter().get_completions(
            Document("/cl", cursor_position=3),
            CompleteEvent(completion_requested=True),
        ),
    )

    assert [completion.text for completion in completions] == ["/clear"]
    assert completions[0].display_meta_text == "清空终端内容"

    verbose_completions = list(
        SlashCommandCompleter().get_completions(
            Document("/v", cursor_position=2),
            CompleteEvent(completion_requested=True),
        ),
    )
    assert [completion.text for completion in verbose_completions] == [
        "/verbose",
    ]


def test_completer_ignores_messages_and_finished_commands() -> None:
    """普通消息和已带参数的输入不应弹出命令候选。"""
    completer = SlashCommandCompleter()
    complete_event = CompleteEvent(text_inserted=True)

    assert list(
        completer.get_completions(Document("你好"), complete_event),
    ) == []
    assert list(
        completer.get_completions(Document("/help extra"), complete_event),
    ) == []
