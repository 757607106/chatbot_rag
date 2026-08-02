"""Rich 事件渲染测试。"""

from io import StringIO

from agentscope.event import (
    ModelCallEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState
from rich.console import Console

from chatbot_rag.cli.renderer import (
    EventRenderer,
    _format_received,
    _looks_like_markdown,
)


def test_renderer_streams_markdown_and_tool_panels() -> None:
    """文本、工具入参和工具结果应使用对应的 Rich 组件呈现。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="## 回答\n\n这是 **Markdown**。",
        ),
    )
    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        ToolCallStartEvent(
            reply_id="reply",
            tool_call_id="tool",
            tool_call_name="knowledge_search",
        ),
    )
    renderer.handle(
        ToolCallDeltaEvent(
            reply_id="reply",
            tool_call_id="tool",
            delta='{"query":"测试"}',
        ),
    )
    renderer.handle(
        ToolCallEndEvent(reply_id="reply", tool_call_id="tool"),
    )
    renderer.handle(
        ToolResultStartEvent(
            reply_id="reply",
            tool_call_id="tool",
            tool_call_name="knowledge_search",
        ),
    )
    renderer.handle(
        ToolResultTextDeltaEvent(
            reply_id="reply",
            tool_call_id="tool",
            delta='{"matches":2}',
        ),
    )
    renderer.handle(
        ToolResultEndEvent(
            reply_id="reply",
            tool_call_id="tool",
            state=ToolResultState.SUCCESS,
        ),
    )
    renderer.handle(
        ModelCallEndEvent(
            reply_id="reply",
            input_tokens=1200,
            output_tokens=80,
        ),
    )
    renderer.finish_reply(outcome="completed")

    rendered = output.getvalue()
    assert "agent：" in rendered
    assert "回答" in rendered
    assert "这是 Markdown。" in rendered
    assert "knowledge_search  ✓" in rendered
    assert "输入" in rendered
    assert '"query"' in rendered
    assert "输出" in rendered
    assert '"matches"' in rendered
    assert "Token 1,200 → 80" in rendered
    assert "tok/s" in rendered
    assert "工具 1" in rendered


def test_renderer_truncates_tool_output_until_verbose_is_enabled() -> None:
    """默认工具面板应限制长度，详细模式应显示完整内容。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=72),
    )
    long_output = "结果" * 1_000

    _render_tool_result(renderer, long_output, tool_call_id="first")

    truncated_render = output.getvalue()
    assert "已省略" in truncated_render
    assert "/verbose" in truncated_render

    output.seek(0)
    output.truncate(0)
    assert renderer.toggle_verbose() is True

    _render_tool_result(renderer, long_output, tool_call_id="second")

    verbose_render = output.getvalue()
    assert "已省略" not in verbose_render
    assert verbose_render.count("结") == 1_000
    assert verbose_render.count("果") == 1_000


def test_renderer_replays_truncated_panel_after_verbose_enabled() -> None:
    """开启 verbose 后应能重放最近一次被截断的工具面板完整内容。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=72),
    )
    long_output = "结果" * 1_000

    _render_tool_result(renderer, long_output, tool_call_id="first")
    assert "已省略" in output.getvalue()

    output.seek(0)
    output.truncate(0)
    assert renderer.toggle_verbose() is True
    assert renderer.replay_truncated_tool_panel() is True

    replayed = output.getvalue()
    assert "最近一次工具调用的完整内容" in replayed
    assert "已省略" not in replayed
    assert replayed.count("结") == 1_000
    # 重放后缓存已清空，不应重复重放。
    assert renderer.replay_truncated_tool_panel() is False


def test_complete_tool_panel_clears_the_truncated_replay_cache() -> None:
    """未截断的工具面板应清除重放缓存，避免重放过期内容。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=72),
    )

    _render_tool_result(renderer, "结果" * 1_000, tool_call_id="first")
    _render_tool_result(renderer, "短结果", tool_call_id="second")

    assert renderer.toggle_verbose() is True
    assert renderer.replay_truncated_tool_panel() is False


def test_help_is_plain_text_without_terminal_colors() -> None:
    """帮助信息不应包含颜色控制序列或装饰面板。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(
            file=output,
            force_terminal=True,
            color_system="standard",
            width=100,
        ),
    )

    renderer.show_help()

    rendered = output.getvalue()
    assert "帮助" in rendered
    assert "/verbose" in rendered
    assert "Ctrl+D" in rendered
    assert "排队" in rendered
    assert "\x1b[" not in rendered
    assert "╭" not in rendered


def test_completed_lines_stream_before_the_text_block_ends() -> None:
    """完整行应在文本块结束前逐行渲染，未完成行等待换行。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="第一行\n第二",
        ),
    )

    streamed = output.getvalue()
    assert "第一行" in streamed
    assert "第二" not in streamed

    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="行\n",
        ),
    )
    assert "第二行" in output.getvalue()

    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")


def test_streamed_lines_render_markdown_without_raw_markers() -> None:
    """流式输出的行应按 Markdown 渲染，不显示原始标记。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="这是 **加粗** 内容\n",
        ),
    )

    rendered = output.getvalue()
    assert "加粗" in rendered
    assert "**" not in rendered

    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")


def test_code_fence_streams_as_one_block_after_closing() -> None:
    """代码围栏应在闭合后作为整体渲染，闭合前不逐行输出。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="```python\nanswer = 42\n",
        ),
    )
    assert "answer" not in output.getvalue()

    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="```\n",
        ),
    )
    assert "answer" in output.getvalue()

    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")


def test_table_rows_are_buffered_and_rendered_together() -> None:
    """连续表格行应聚合成一个表格渲染。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |\n说明\n",
        ),
    )

    rendered = output.getvalue()
    assert "名称" in rendered
    assert "苹果" in rendered
    assert "说明" in rendered

    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")


def test_activity_listener_tracks_reply_and_tool_progress() -> None:
    """活动状态监听器应依次收到思考、工具进度和空闲通知。"""
    renderer = EventRenderer(
        Console(file=StringIO(), force_terminal=False, width=100),
    )
    activities: list[str | None] = []
    renderer.set_activity_listener(activities.append)

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")

    assert activities == ["正在思考...", None]

    activities.clear()
    _render_tool_result(renderer, "x" * 100, tool_call_id="tool")

    assert "正在准备工具 long_tool..." in activities
    assert any(
        activity is not None
        and "正在执行工具 long_tool" in activity
        and "已接收 100 字符" in activity
        for activity in activities
    )
    assert activities[-1] is None


def test_plain_text_block_is_printed_verbatim() -> None:
    """不含 Markdown 语法的文本块应逐字打印，保留原始换行。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.begin_reply()
    renderer.handle(TextBlockStartEvent(reply_id="reply", block_id="text"))
    renderer.handle(
        TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="第一行\n第二行，snake_case 与 price * quantity",
        ),
    )
    renderer.handle(TextBlockEndEvent(reply_id="reply", block_id="text"))
    renderer.finish_reply(outcome="completed")

    # 非终端输出会把每行补齐到全宽，归一化行尾空格后比较内容。
    normalized = "\n".join(
        line.rstrip() for line in output.getvalue().splitlines()
    )
    assert "  第一行\n  第二行，snake_case 与 price * quantity" in normalized


def test_markdown_hint_distinguishes_syntax_from_plain_text() -> None:
    """Markdown 特征检测应命中常见语法并排除纯文本。"""
    assert _looks_like_markdown("## 标题")
    assert _looks_like_markdown("这是 **加粗** 内容")
    assert _looks_like_markdown("- 列表项")
    assert _looks_like_markdown("1. 有序项")
    assert _looks_like_markdown("`inline` 代码")
    assert _looks_like_markdown("```python\ncode\n```")
    assert _looks_like_markdown("[链接](https://example.com)")
    assert _looks_like_markdown("| 表头 |")
    assert not _looks_like_markdown("普通多行文本\n第二行")
    assert not _looks_like_markdown("snake_case 与 price * quantity")
    assert not _looks_like_markdown("中文 #话题 不含标题语法")


def test_user_message_continuation_lines_align_with_content() -> None:
    """多行用户消息的续行应与首行内容对齐。"""
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )

    renderer.show_user_message("第一行\n第二行")

    assert "user：第一行\n      第二行" in output.getvalue()


def test_format_received_compacts_character_counts() -> None:
    """工具已接收字符数应按量级压缩显示。"""
    assert _format_received(128) == "128 字符"
    assert _format_received(1_536) == "1.5k 字符"
    assert _format_received(12_000) == "12k 字符"


def _render_tool_result(
    renderer: EventRenderer,
    output: str,
    tool_call_id: str,
) -> None:
    """为面板长度测试生成一次完整工具事件生命周期。"""
    renderer.begin_reply()
    renderer.handle(
        ToolCallStartEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
            tool_call_name="long_tool",
        ),
    )
    renderer.handle(
        ToolCallDeltaEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
            delta='{"query":"测试"}',
        ),
    )
    renderer.handle(
        ToolCallEndEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
        ),
    )
    renderer.handle(
        ToolResultStartEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
            tool_call_name="long_tool",
        ),
    )
    renderer.handle(
        ToolResultTextDeltaEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
            delta=output,
        ),
    )
    renderer.handle(
        ToolResultEndEvent(
            reply_id="reply",
            tool_call_id=tool_call_id,
            state=ToolResultState.SUCCESS,
        ),
    )
    renderer.finish_reply(outcome="completed")
