"""使用 Rich 渲染 AgentScope 回复事件。"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentscope.event import (
    AgentEvent,
    ExceedMaxItersEvent,
    ModelCallEndEvent,
    ModelCallStartEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultDataDeltaEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from rich import box
from rich.console import Console, Group, RenderableType
from rich.constrain import Constrain
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


@dataclass(slots=True)
class _ToolDisplay:
    """聚合一次工具调用的增量输入和输出。"""

    name: str
    input_parts: list[str] = field(default_factory=list)
    output_parts: list[str] = field(default_factory=list)
    output_chars: int = 0
    started_at: float = field(default_factory=time.perf_counter)


@dataclass(frozen=True, slots=True)
class _CompletedToolPanel:
    """一次已完成工具调用的完整展示数据，用于 verbose 重放。"""

    name: str
    input_text: str
    output_text: str
    state: str
    duration: float


MAX_TOOL_INPUT_CHARS = 800
MAX_TOOL_OUTPUT_CHARS = 1_600
MAX_CONTENT_WIDTH = 110

# 区分需要完整 Markdown 渲染的文本块与可原样打印的纯文本。
_MARKDOWN_HINT = re.compile(
    r"^\s{0,3}#{1,6}\s"  # ATX 标题
    r"|^\s*(?:[-*+]|\d+\.)\s"  # 列表项
    r"|^\s*>\s"  # 引用
    r"|^\s*\|"  # 表格行
    r"|^\s*```"  # 围栏代码块
    r"|\*\*[^*]+\*\*"  # 加粗
    r"|__[^_]+__"
    r"|\*[^*\n]+\*"  # 斜体
    r"|~~[^~]+~~"  # 删除线
    r"|`[^`\n]+`"  # 行内代码
    r"|!?\[[^\]]+\]\([^)]+\)"  # 链接或图片
    r"|^\s*(?:-{3,}|\*{3,})\s*$",  # 分隔线
    re.MULTILINE,
)


class EventRenderer:
    """把 AgentScope 2.0.5 事件映射为 Rich 终端组件。

    会话期间所有输出都是追加式的：不使用 Rich `Live`/`Status` 等
    需要原地重绘的组件，避免与 prompt_toolkit 活动输入框争夺终端。
    回复活动状态（思考、工具执行）通过监听器传给输入区显示。
    """

    def __init__(self, console: Console) -> None:
        """使用指定 Rich 控制台初始化渲染状态。"""
        self._console = console
        self._activity: str | None = None
        self._activity_listener: Callable[[str | None], None] | None = None
        self._active_text_block_id: str | None = None
        self._pending_text = ""
        self._fence_lines: list[str] | None = None
        self._table_lines: list[str] = []
        self._assistant_header_printed = False
        self._tools: dict[str, _ToolDisplay] = {}
        self._verbose = False
        self._truncated_panel: _CompletedToolPanel | None = None
        self._reply_started_at: float | None = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_call_count = 0

    def set_activity_listener(
        self,
        listener: Callable[[str | None], None] | None,
    ) -> None:
        """注册回复活动状态回调，供输入区显示思考和工具进度。"""
        self._activity_listener = listener

    def show_welcome(
        self,
        agent_name: str,
        session_context: str | None = None,
    ) -> None:
        """显示紧凑的会话标题和运行上下文。"""
        header = Text.assemble(
            ("chatbot_rag", "bold cyan"),
            ("  ", ""),
            (agent_name, "bold"),
        )
        if session_context:
            header.append(" · ", style="dim")
            header.append(session_context, style="dim")
        self._console.print(Constrain(header, width=MAX_CONTENT_WIDTH))
        self._console.print(
            Constrain(
                Text(
                    "Enter 发送 · Esc+Enter 换行 · Esc 中断 · "
                    "↑/↓ 历史 · /help · Ctrl+D 退出",
                    style="dim",
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )
        self._console.print()

    def show_help(self) -> None:
        """使用无颜色纯文本显示命令和快捷键。"""
        help_text = Text(
            "帮助\n"
            "  /help       显示帮助\n"
            "  /clear      清空终端\n"
            "  /verbose    切换完整工具输出，开启时重放最近被截断的工具结果\n"
            "  /exit       退出聊天\n\n"
            "快捷键\n"
            "  Enter       发送\n"
            "  Esc+Enter   换行\n"
            "  ↑/↓         浏览历史\n"
            "  Esc         中断当前回复\n"
            "  Ctrl+C      取消当前输入\n"
            "  Ctrl+D      退出聊天\n\n"
            "提示\n"
            "  回复生成期间可继续输入，消息会按提交顺序排队处理",
        )
        self._console.print(
            Constrain(
                help_text,
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def show_notice(self, message: str) -> None:
        """显示不打断会话的提示。"""
        self._console.print(
            Constrain(
                Text(f"› {message}", style="yellow"),
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def show_queued(self, queue_position: int) -> None:
        """确认新消息已在当前回复之后排队。"""
        self._console.print(
            Constrain(
                Text(
                    f"✓ 消息已排队 · 队列位置 {queue_position}",
                    style="dim cyan",
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def show_user_message(self, message: str) -> None:
        """在同一行显示用户标签和消息内容，续行与首行内容对齐。"""
        self._console.print()
        self._console.print(
            Constrain(
                Text.assemble(
                    ("user：", "bold cyan"),
                    (message.replace("\n", "\n      "), ""),
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def toggle_verbose(self) -> bool:
        """切换工具面板是否显示完整内容，并返回新状态。"""
        self._verbose = not self._verbose
        return self._verbose

    def replay_truncated_tool_panel(self) -> bool:
        """重放最近一次被截断工具面板的完整内容。

        Returns:
            存在可重放的面板时为 ``True``，否则为 ``False``。
        """
        if self._truncated_panel is None:
            return False
        record = self._truncated_panel
        self._truncated_panel = None
        self._console.print(
            Constrain(
                Text("› 最近一次工具调用的完整内容", style="dim"),
                width=MAX_CONTENT_WIDTH,
            ),
        )
        self._print_tool_panel(record, full=True)
        return True

    def clear(self) -> None:
        """清空当前终端显示。"""
        self._console.clear()

    def show_error(self, message: str) -> None:
        """使用错误面板显示可恢复异常。"""
        self._console.print(
            Constrain(
                Panel(
                    Text(message),
                    title="错误",
                    border_style="red",
                    box=box.ROUNDED,
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def begin_reply(self) -> None:
        """重置本轮状态并提示正在思考。"""
        self.finish_reply(outcome=None)
        self._active_text_block_id = None
        self._assistant_header_printed = False
        self._tools = {}
        self._reply_started_at = time.perf_counter()
        self._input_tokens = 0
        self._output_tokens = 0
        self._tool_call_count = 0
        self._set_activity("正在思考...")

    def handle(self, event: AgentEvent) -> None:
        """根据具体事件类型增量更新终端显示。"""
        if isinstance(event, ModelCallStartEvent):
            self._set_activity("正在思考...")
        elif isinstance(event, ModelCallEndEvent):
            self._input_tokens += event.input_tokens
            self._output_tokens += event.output_tokens
        elif isinstance(event, ThinkingBlockStartEvent):
            self._set_activity("正在思考...")
        elif isinstance(event, TextBlockStartEvent):
            self._start_text(event.block_id)
        elif isinstance(event, TextBlockDeltaEvent):
            self._append_text(event.block_id, event.delta)
        elif isinstance(event, TextBlockEndEvent):
            self._end_text(event.block_id)
        elif isinstance(event, ToolCallStartEvent):
            self._start_tool_call(event)
        elif isinstance(event, ToolCallDeltaEvent):
            self._append_tool_input(event)
        elif isinstance(event, ToolCallEndEvent):
            self._end_tool_call(event)
        elif isinstance(event, ToolResultStartEvent):
            self._start_tool_result(event)
        elif isinstance(event, ToolResultTextDeltaEvent):
            self._append_tool_output(event.tool_call_id, event.delta)
        elif isinstance(event, ToolResultDataDeltaEvent):
            self._append_tool_data(event)
        elif isinstance(event, ToolResultEndEvent):
            self._end_tool_result(event)
        elif isinstance(event, ExceedMaxItersEvent):
            self.show_notice("agent 已达到最大推理轮数。")
        elif isinstance(event, ReplyEndEvent) and event.error is not None:
            self.show_error(event.error.message)

    def finish_reply(self, outcome: str | None = None) -> None:
        """冲刷未完成文本，并按结果显示本轮运行指标。"""
        if self._active_text_block_id is not None:
            self._flush_text()
            self._active_text_block_id = None
        self._set_activity(None)
        if outcome == "completed":
            self._show_reply_metrics()
        self._reply_started_at = None

    def _set_activity(self, message: str | None) -> None:
        """更新回复活动状态并通知输入区，相同状态不重复触发。"""
        if message == self._activity:
            return
        self._activity = message
        if self._activity_listener is not None:
            self._activity_listener(message)

    def _start_text(self, block_id: str) -> None:
        """开始文本块：打印一次 agent 标签，并重置逐行渲染状态。"""
        if self._active_text_block_id is not None:
            self._end_text(self._active_text_block_id)
        self._set_activity(None)
        if not self._assistant_header_printed:
            self._console.print()
            self._console.print(
                Constrain(
                    Text("agent：", style="bold"),
                    width=MAX_CONTENT_WIDTH,
                ),
            )
            self._assistant_header_printed = True
        self._active_text_block_id = block_id
        self._pending_text = ""
        self._fence_lines = None
        self._table_lines = []

    def _append_text(self, block_id: str, delta: str) -> None:
        """追加文本增量，并逐行渲染已完成的内容。"""
        if self._active_text_block_id != block_id:
            self._start_text(block_id)
        self._pending_text += delta
        while "\n" in self._pending_text:
            line, self._pending_text = self._pending_text.split("\n", 1)
            self._render_line(line)

    def _end_text(self, block_id: str) -> None:
        """冲刷文本块中尚未换行的剩余内容。"""
        if self._active_text_block_id != block_id:
            return
        self._flush_text()
        self._active_text_block_id = None

    def _render_line(self, line: str) -> None:
        """按行渲染：代码围栏和表格聚合成整体，其余内容逐行输出。"""
        if self._fence_lines is not None:
            self._fence_lines.append(line)
            if line.strip().startswith("```"):
                self._print_text_unit("\n".join(self._fence_lines))
                self._fence_lines = None
            return
        stripped = line.strip()
        if stripped.startswith("```"):
            self._flush_table()
            self._fence_lines = [line]
            return
        if stripped.startswith("|"):
            self._table_lines.append(line)
            return
        self._flush_table()
        self._print_text_unit(line)

    def _flush_table(self) -> None:
        """把连续的表格行作为一个整体渲染。"""
        if self._table_lines:
            self._print_text_unit("\n".join(self._table_lines))
            self._table_lines = []

    def _flush_text(self) -> None:
        """渲染块结束时未换行的剩余文本和未闭合的围栏、表格。"""
        self._flush_table()
        if self._fence_lines is not None:
            # 未闭合的代码围栏交给 Markdown 容错渲染为代码块。
            self._print_text_unit("\n".join(self._fence_lines))
            self._fence_lines = None
        if self._pending_text:
            self._print_text_unit(self._pending_text)
            self._pending_text = ""

    def _print_text_unit(self, content: str) -> None:
        """渲染一个追加式文本单元：空行原样、纯文本逐字、其余按 Markdown。"""
        if not content.strip():
            self._console.print()
            return
        renderable: RenderableType = (
            Markdown(content) if _looks_like_markdown(content) else Text(content)
        )
        self._console.print(
            Constrain(
                Padding(renderable, (0, 0, 0, 2)),
                width=MAX_CONTENT_WIDTH,
            ),
        )

    def _start_tool_call(self, event: ToolCallStartEvent) -> None:
        """记录工具名称并显示准备状态。"""
        self._set_activity(f"正在准备工具 {event.tool_call_name}...")
        self._tools[event.tool_call_id] = _ToolDisplay(
            name=event.tool_call_name,
        )
        self._tool_call_count += 1

    def _append_tool_input(self, event: ToolCallDeltaEvent) -> None:
        """追加工具调用的 JSON 参数片段。"""
        tool = self._tools.setdefault(
            event.tool_call_id,
            _ToolDisplay(name="unknown"),
        )
        tool.input_parts.append(event.delta)

    def _end_tool_call(self, event: ToolCallEndEvent) -> None:
        """完成工具入参聚合，并切换到执行状态。"""
        tool = self._tools.setdefault(
            event.tool_call_id,
            _ToolDisplay(name="unknown"),
        )
        self._set_activity(f"正在执行工具 {tool.name}...")

    def _start_tool_result(self, event: ToolResultStartEvent) -> None:
        """确保结果事件能够关联到对应的工具显示状态。"""
        tool = self._tools.setdefault(
            event.tool_call_id,
            _ToolDisplay(name=event.tool_call_name),
        )
        self._set_activity(f"正在执行工具 {tool.name}...")

    def _append_tool_output(self, tool_call_id: str, delta: str) -> None:
        """追加工具的文本返回片段，并在输入区反馈已接收的数据量。"""
        tool = self._tools.setdefault(
            tool_call_id,
            _ToolDisplay(name="unknown"),
        )
        tool.output_parts.append(delta)
        tool.output_chars += len(delta)
        self._set_activity(
            f"正在执行工具 {tool.name}..."
            f"（已接收 {_format_received(tool.output_chars)}）",
        )

    def _append_tool_data(self, event: ToolResultDataDeltaEvent) -> None:
        """把非文本工具输出转换为可读摘要。"""
        if event.url is not None:
            summary = f"[{event.media_type}] {event.url}"
        else:
            data_length = len(event.data or "")
            summary = f"[{event.media_type}] base64 数据（{data_length} 字符）"
        self._append_tool_output(event.tool_call_id, summary)

    def _end_tool_result(self, event: ToolResultEndEvent) -> None:
        """聚合工具展示数据并渲染面板，缓存被截断的面板供重放。"""
        tool = self._tools.setdefault(
            event.tool_call_id,
            _ToolDisplay(name="unknown"),
        )
        record = _CompletedToolPanel(
            name=tool.name,
            input_text="".join(tool.input_parts),
            output_text="".join(tool.output_parts),
            state=str(event.state),
            duration=time.perf_counter() - tool.started_at,
        )
        truncated = self._print_tool_panel(record, full=self._verbose)
        # 仅保留最近一次被截断的面板，供 /verbose 开启后立即回看。
        self._truncated_panel = record if truncated else None
        self._set_activity("正在思考...")

    def _print_tool_panel(
        self,
        record: _CompletedToolPanel,
        *,
        full: bool,
    ) -> bool:
        """使用单个紧凑面板展示工具入参、结果、状态和耗时。

        Args:
            record: 已完成工具调用的完整展示数据。
            full: 为 ``True`` 时不截断输入和输出内容。

        Returns:
            面板内容因长度限制被截断时为 ``True``。
        """
        input_limit = None if full else MAX_TOOL_INPUT_CHARS
        output_limit = None if full else MAX_TOOL_OUTPUT_CHARS
        input_renderable, input_truncated = _structured_renderable(
            record.input_text,
            input_limit,
        )
        output_renderable, output_truncated = _structured_renderable(
            record.output_text,
            output_limit,
        )
        symbol, border_style = _tool_state_style(record.state)
        panel_box = (
            box.MINIMAL if self._console.size.width < 80 else box.ROUNDED
        )
        self._console.print(
            Constrain(
                Panel(
                    Group(
                        Text("输入", style="dim"),
                        Padding(input_renderable, (0, 0, 0, 2)),
                        Text("输出", style="dim"),
                        Padding(output_renderable, (0, 0, 0, 2)),
                    ),
                    title=Text(
                        f"{record.name}  {symbol} {record.duration:.1f}s",
                        style=f"bold {border_style}",
                    ),
                    border_style=border_style,
                    box=panel_box,
                    padding=(0, 1),
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )
        return input_truncated or output_truncated

    def _show_reply_metrics(self) -> None:
        """在回复结束后显示耗时、token 和工具调用数量。"""
        if self._reply_started_at is None:
            return
        duration = time.perf_counter() - self._reply_started_at
        metrics = [f"耗时 {duration:.1f}s"]
        if self._input_tokens or self._output_tokens:
            metrics.append(
                f"Token {self._input_tokens:,} → {self._output_tokens:,}",
            )
            if self._output_tokens and duration > 0:
                metrics.append(
                    f"{self._output_tokens / duration:.0f} tok/s",
                )
        if self._tool_call_count:
            metrics.append(f"工具 {self._tool_call_count}")
        self._console.print(
            Constrain(
                Padding(
                    Text(" · ".join(metrics), style="dim"),
                    (0, 0, 0, 2),
                ),
                width=MAX_CONTENT_WIDTH,
            ),
        )


def _structured_renderable(
    value: str,
    max_chars: int | None,
) -> tuple[RenderableType, bool]:
    """优先格式化 JSON，并按显示模式安全截断长内容。

    Returns:
        渲染对象，以及内容是否因长度限制被截断。
    """
    if not value:
        return Text("（无内容）", style="dim"), False
    try:
        parsed: Any = json.loads(value)
    except json.JSONDecodeError:
        truncated = _truncate(value, max_chars)
        return Text(truncated), truncated != value
    formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
    truncated_json = _truncate(formatted, max_chars)
    return (
        Syntax(
            truncated_json,
            "json",
            theme="ansi_dark",
            background_color="default",
            word_wrap=True,
        ),
        truncated_json != formatted,
    )


def _looks_like_markdown(content: str) -> bool:
    """检测文本块是否包含会被 Markdown 渲染改变的常见语法。"""
    return _MARKDOWN_HINT.search(content) is not None


def _format_received(count: int) -> str:
    """把工具已返回的字符数格式化为紧凑的可读文本。"""
    if count >= 10_000:
        return f"{count / 1_000:.0f}k 字符"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k 字符"
    return f"{count} 字符"


def _truncate(value: str, max_chars: int | None) -> str:
    """截断过长工具内容，并给出查看完整内容的命令提示。"""
    if max_chars is None or len(value) <= max_chars:
        return value
    omitted_chars = len(value) - max_chars
    return (
        f"{value[:max_chars]}\n"
        f"… 已省略 {omitted_chars} 字符，输入 /verbose 查看完整内容。"
    )


def _tool_state_style(state: str) -> tuple[str, str]:
    """把 AgentScope 工具结果状态映射为稳定符号和颜色。"""
    styles = {
        "success": ("✓", "green"),
        "error": ("✕", "red"),
        "interrupted": ("■", "yellow"),
        "denied": ("!", "yellow"),
        "running": ("…", "cyan"),
    }
    return styles.get(state, ("?", "yellow"))
