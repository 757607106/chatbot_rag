"""交互式 CLI 会话循环测试。"""

import asyncio
from collections.abc import AsyncIterator
from io import StringIO

import pytest
from agentscope.event import (
    AgentEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import AssistantMsg, Msg
from rich.console import Console

from chatbot_rag.cli.application import CliApplication
from chatbot_rag.cli.input_session import ReplyInterrupt
from chatbot_rag.cli.renderer import EventRenderer
from chatbot_rag.services import ChatService


class FakeInputSession:
    """按顺序返回预设输入。"""

    def __init__(self, messages: list[str]) -> None:
        """保存待返回消息。"""
        self._messages = iter(messages)
        self.read_count = 0
        self.statuses: list[int] = []
        self.activities: list[str | None] = []

    async def read(self) -> str:
        """返回下一条输入。"""
        self.read_count += 1
        return next(self._messages)

    def update_status(self, queue_size: int) -> None:
        """记录应用同步的队列状态。"""
        self.statuses.append(queue_size)

    def update_activity(self, activity: str | None) -> None:
        """记录应用同步的回复活动状态。"""
        self.activities.append(activity)


class StreamingFakeAgent:
    """记录输入并返回一段流式 Markdown。"""

    def __init__(self) -> None:
        """以空输入记录初始化。"""
        self.received: Msg | None = None

    async def reply(self, inputs: Msg) -> Msg:
        """返回非流式替身回复。"""
        self.received = inputs
        return AssistantMsg(name="assistant", content="完成")

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """返回完整的文本事件生命周期。"""
        self.received = inputs
        yield ReplyStartEvent(
            session_id="session",
            reply_id="reply",
            name="assistant",
        )
        yield TextBlockStartEvent(reply_id="reply", block_id="text")
        yield TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="**完成**",
        )
        yield TextBlockEndEvent(reply_id="reply", block_id="text")
        yield ReplyEndEvent(session_id="session", reply_id="reply")


class DelayedStreamingAgent(StreamingFakeAgent):
    """首轮回复暂停期间记录后续输入是否已入队。"""

    def __init__(self) -> None:
        """创建用于协调测试的事件和调用记录。"""
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.messages: list[str] = []

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """首轮回复等待测试放行，后续回复直接完成。"""
        self.messages.append(inputs.get_text_content() or "")
        if len(self.messages) == 1:
            self.started.set()
            await self.release.wait()
        yield ReplyStartEvent(
            session_id="session",
            reply_id=f"reply-{len(self.messages)}",
            name="assistant",
        )
        yield ReplyEndEvent(
            session_id="session",
            reply_id=f"reply-{len(self.messages)}",
        )


class InterruptingInputSession:
    """在首轮回复开始后发送中断信号和退出命令。"""

    def __init__(self, reply_started: asyncio.Event) -> None:
        """保存回复启动事件并初始化读取次数。"""
        self._reply_started = reply_started
        self._read_count = 0

    async def read(self) -> str:
        """依次返回问题、中断信号和退出命令。"""
        self._read_count += 1
        if self._read_count == 1:
            return "需要中断的问题"
        if self._read_count == 2:
            await self._reply_started.wait()
            raise ReplyInterrupt
        return "/exit"

    def update_status(self, queue_size: int) -> None:
        """接收状态更新，本测试不需要额外记录。"""
        del queue_size

    def update_activity(self, activity: str | None) -> None:
        """接收活动状态更新，本测试不需要额外记录。"""
        del activity


class InterruptibleAgent(StreamingFakeAgent):
    """持续等待，直到 CLI 取消当前流式回复。"""

    def __init__(self) -> None:
        """创建回复开始和取消完成事件。"""
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """产生开始事件后等待取消。"""
        self.received = inputs
        self.started.set()
        yield ReplyStartEvent(
            session_id="session",
            reply_id="reply",
            name="assistant",
        )
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


class WaitingInputSession:
    """提交首条消息后持续等待，用于应用取消测试。"""

    def __init__(self) -> None:
        """初始化读取次数。"""
        self._read_count = 0

    async def read(self) -> str:
        """首次返回问题，随后保持输入任务存活。"""
        self._read_count += 1
        if self._read_count == 1:
            return "持续执行的问题"
        await asyncio.Event().wait()
        raise AssertionError("等待任务不应正常返回")

    def update_status(self, queue_size: int) -> None:
        """接收状态更新，本测试不需要额外记录。"""
        del queue_size

    def update_activity(self, activity: str | None) -> None:
        """接收活动状态更新，本测试不需要额外记录。"""
        del activity


class BurstStreamingAgent(StreamingFakeAgent):
    """首轮连续产生大量文本事件的智能体替身。"""

    def __init__(self) -> None:
        """初始化事件计数和回复启动信号。"""
        super().__init__()
        self.started = asyncio.Event()
        self.events_emitted = 0
        self.messages: list[str] = []

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """首轮产生五千个增量，后续回复直接结束。"""
        self.messages.append(inputs.get_text_content() or "")
        reply_id = f"reply-{len(self.messages)}"
        yield ReplyStartEvent(
            session_id="session",
            reply_id=reply_id,
            name="assistant",
        )
        if len(self.messages) == 1:
            self.started.set()
            yield TextBlockStartEvent(reply_id=reply_id, block_id="text")
            for _ in range(5_000):
                self.events_emitted += 1
                yield TextBlockDeltaEvent(
                    reply_id=reply_id,
                    block_id="text",
                    delta="x",
                )
            yield TextBlockEndEvent(reply_id=reply_id, block_id="text")
        yield ReplyEndEvent(session_id="session", reply_id=reply_id)


class BurstInputSession:
    """在大量事件到达期间提交第二条消息。"""

    def __init__(self, agent: BurstStreamingAgent) -> None:
        """保存智能体计数器并初始化读取状态。"""
        self._agent = agent
        self._read_count = 0
        self.events_before_second_input: int | None = None

    async def read(self) -> str:
        """依次提交首条消息、排队消息和退出命令。"""
        self._read_count += 1
        if self._read_count == 1:
            return "第一条"
        if self._read_count == 2:
            await self._agent.started.wait()
            self.events_before_second_input = self._agent.events_emitted
            return "第二条"
        return "/exit"

    def update_status(self, queue_size: int) -> None:
        """接收状态更新，本测试通过事件计数验证调度。"""
        del queue_size

    def update_activity(self, activity: str | None) -> None:
        """接收活动状态更新，本测试不需要额外记录。"""
        del activity


@pytest.mark.asyncio
async def test_application_handles_commands_and_streams_a_reply() -> None:
    """本地命令不应发送给 Agent，普通消息应进入事件流。"""
    agent = StreamingFakeAgent()
    output = StringIO()
    renderer = EventRenderer(
        Console(file=output, force_terminal=False, width=100),
    )
    application = CliApplication(
        ChatService(agent),
        FakeInputSession(
            [
                "/clear",
                "/help",
                "/verbose",
                "/unknown",
                "问题",
                "/exit",
            ],
        ),
        renderer,
        "assistant",
    )

    await application.run()

    assert agent.received is not None
    assert agent.received.get_text_content() == "问题"
    rendered = output.getvalue()
    assert "帮助" in rendered
    assert rendered.count("chatbot_rag") == 2
    assert "完整工具输出已开启" in rendered
    assert "未知命令" in rendered
    assert "user：问题" in rendered
    assert "完成" in rendered


@pytest.mark.asyncio
async def test_application_queues_input_while_reply_is_streaming() -> None:
    """模型回复未结束时，输入任务仍应接收并排队下一条消息。"""
    agent = DelayedStreamingAgent()
    input_session = FakeInputSession(["第一条", "第二条", "/exit"])
    application = CliApplication(
        ChatService(agent),
        input_session,
        EventRenderer(
            Console(file=StringIO(), force_terminal=False, width=100),
        ),
        "assistant",
    )

    run_task = asyncio.create_task(application.run())
    await asyncio.wait_for(agent.started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert input_session.read_count == 3
    assert agent.messages == ["第一条"]

    agent.release.set()
    await asyncio.wait_for(run_task, timeout=1)

    assert agent.messages == ["第一条", "第二条"]


@pytest.mark.asyncio
async def test_application_interrupts_only_the_active_reply() -> None:
    """Esc 信号应取消当前回复，并允许队列继续处理退出命令。"""
    agent = InterruptibleAgent()
    output = StringIO()
    application = CliApplication(
        ChatService(agent),
        InterruptingInputSession(agent.started),
        EventRenderer(
            Console(file=output, force_terminal=False, width=100),
        ),
        "assistant",
    )

    await asyncio.wait_for(application.run(), timeout=1)

    assert agent.cancelled.is_set()
    assert "已中断当前回复" in output.getvalue()


@pytest.mark.asyncio
async def test_application_propagates_external_cancellation() -> None:
    """应用级取消不应被误判为用户按下 Esc。"""
    agent = InterruptibleAgent()
    application = CliApplication(
        ChatService(agent),
        WaitingInputSession(),
        EventRenderer(
            Console(file=StringIO(), force_terminal=False, width=100),
        ),
        "assistant",
    )
    run_task = asyncio.create_task(application.run())
    await asyncio.wait_for(agent.started.wait(), timeout=1)

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert agent.cancelled.is_set()


class FailingAgent(StreamingFakeAgent):
    """先产生部分文本再抛出异常的智能体替身。"""

    async def reply_stream(self, inputs: Msg) -> AsyncIterator[AgentEvent]:
        """输出部分内容后模拟模型调用失败。"""
        self.received = inputs
        yield ReplyStartEvent(
            session_id="session",
            reply_id="reply",
            name="assistant",
        )
        yield TextBlockStartEvent(reply_id="reply", block_id="text")
        yield TextBlockDeltaEvent(
            reply_id="reply",
            block_id="text",
            delta="部分内容",
        )
        raise RuntimeError("模型调用失败")


@pytest.mark.asyncio
async def test_application_prints_partial_reply_before_error_panel() -> None:
    """回复中途失败时，已生成的部分内容应先于错误面板显示。"""
    agent = FailingAgent()
    output = StringIO()
    application = CliApplication(
        ChatService(agent),
        FakeInputSession(["问题", "/exit"]),
        EventRenderer(
            Console(file=output, force_terminal=False, width=100),
        ),
        "assistant",
    )

    await asyncio.wait_for(application.run(), timeout=1)

    rendered = output.getvalue()
    assert "部分内容" in rendered
    assert "模型调用失败" in rendered
    assert rendered.index("部分内容") < rendered.index("模型调用失败")


@pytest.mark.asyncio
async def test_application_yields_input_during_large_event_burst() -> None:
    """大量连续事件不得占满事件循环并阻塞后续输入。"""
    agent = BurstStreamingAgent()
    input_session = BurstInputSession(agent)
    output = StringIO()
    application = CliApplication(
        ChatService(agent),
        input_session,
        EventRenderer(
            Console(file=output, force_terminal=False, width=100),
        ),
        "assistant",
    )

    await asyncio.wait_for(application.run(), timeout=1)

    assert input_session.events_before_second_input is not None
    assert input_session.events_before_second_input < 5_000
    assert agent.messages == ["第一条", "第二条"]
    assert "消息已排队" in output.getvalue()


class QueuingInputSession:
    """在首轮回复开始后提交第二条消息，验证排队时立即显示内容。"""

    def __init__(self, reply_started: asyncio.Event) -> None:
        """保存回复启动事件并初始化读取次数。"""
        self._reply_started = reply_started
        self._read_count = 0

    async def read(self) -> str:
        """依次提交首条消息、等待回复开始后提交第二条、最后退出。"""
        self._read_count += 1
        if self._read_count == 1:
            return "第一条"
        if self._read_count == 2:
            await self._reply_started.wait()
            return "第二条"
        return "/exit"

    def update_status(self, queue_size: int) -> None:
        """接收状态更新，本测试不需要额外记录。"""
        del queue_size

    def update_activity(self, activity: str | None) -> None:
        """接收活动状态更新，本测试不需要额外记录。"""
        del activity


@pytest.mark.asyncio
async def test_application_shows_queued_message_immediately() -> None:
    """回复期间提交的消息应立即显示内容，而非等到回复完成后才出现。"""
    agent = DelayedStreamingAgent()
    output = StringIO()
    application = CliApplication(
        ChatService(agent),
        QueuingInputSession(agent.started),
        EventRenderer(
            Console(file=output, force_terminal=False, width=100),
        ),
        "assistant",
    )

    run_task = asyncio.create_task(application.run())
    await asyncio.wait_for(agent.started.wait(), timeout=1)
    await asyncio.sleep(0.05)

    # 第一条回复暂停期间，第二条消息已提交并应显示在输出中。
    rendered = output.getvalue()
    assert "user：第一条" in rendered
    assert "user：第二条" in rendered
    assert "消息已排队" in rendered

    agent.release.set()
    await asyncio.wait_for(run_task, timeout=1)
