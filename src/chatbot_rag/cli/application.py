"""交互式 CLI 会话循环。"""

from __future__ import annotations

import asyncio
from typing import Protocol

from chatbot_rag.cli.input_session import ReplyInterrupt
from chatbot_rag.cli.renderer import EventRenderer
from chatbot_rag.services import ChatService


class InputSession(Protocol):
    """CLI 所需的最小异步输入边界。"""

    async def read(self) -> str:
        """读取一条用户输入。"""

    def update_status(self, queue_size: int) -> None:
        """更新输入区的消息队列状态。"""

    def update_activity(self, activity: str | None) -> None:
        """更新输入区的回复活动状态。"""


class CliApplication:
    """协调终端输入、本地命令和聊天事件流。"""

    def __init__(
        self,
        service: ChatService,
        input_session: InputSession,
        renderer: EventRenderer,
        agent_name: str,
        session_context: str | None = None,
    ) -> None:
        """使用协议无关服务和终端组件初始化 CLI。"""
        self._service = service
        self._input = input_session
        self._renderer = renderer
        self._renderer.set_activity_listener(input_session.update_activity)
        self._agent_name = agent_name
        self._session_context = session_context
        self._active_reply_task: asyncio.Task[None] | None = None
        self._reply_interrupt_requested = False

    async def run(self) -> None:
        """并行读取输入并顺序处理消息队列，直到用户退出。"""
        self._renderer.show_welcome(
            self._agent_name,
            self._session_context,
        )
        message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._input.update_status(queue_size=0)
        await asyncio.gather(
            self._read_messages(message_queue),
            self._process_messages(message_queue),
        )

    async def _read_messages(
        self,
        message_queue: asyncio.Queue[str | None],
    ) -> None:
        """持续读取终端输入，使模型流式输出不会阻塞下一条消息。"""
        while True:
            try:
                raw_input = await self._input.read()
            except EOFError:
                await message_queue.put(None)
                return
            except KeyboardInterrupt:
                self._renderer.show_notice("已取消当前输入。")
                continue
            except ReplyInterrupt:
                if self._active_reply_task is None:
                    self._renderer.show_notice("当前没有正在生成的回复。")
                else:
                    self._reply_interrupt_requested = True
                    self._active_reply_task.cancel()
                continue

            message = raw_input.strip()
            if message and not message.startswith("/"):
                # 提交时立即显示用户消息，避免回复期间排队消息完全不可见。
                self._renderer.show_user_message(message)
            await message_queue.put(raw_input)
            if message and not message.startswith("/"):
                if self._active_reply_task is not None:
                    self._renderer.show_queued(message_queue.qsize())
            self._input.update_status(
                queue_size=(
                    message_queue.qsize()
                    if self._active_reply_task is not None
                    else max(message_queue.qsize() - 1, 0)
                ),
            )
            if message == "/exit":
                return

    async def _process_messages(
        self,
        message_queue: asyncio.Queue[str | None],
    ) -> None:
        """按提交顺序执行本地命令或调用一次智能体回复。"""
        while True:
            raw_input = await message_queue.get()
            self._input.update_status(
                queue_size=message_queue.qsize(),
            )
            if raw_input is None:
                return
            message = raw_input.strip()
            if not message:
                continue
            if message == "/exit":
                return
            if message == "/help":
                self._renderer.show_help()
                continue
            if message == "/clear":
                self._renderer.clear()
                self._renderer.show_welcome(
                    self._agent_name,
                    self._session_context,
                )
                continue
            if message == "/verbose":
                verbose_enabled = self._renderer.toggle_verbose()
                state = "开启" if verbose_enabled else "关闭"
                self._renderer.show_notice(f"完整工具输出已{state}。")
                if verbose_enabled:
                    self._renderer.replay_truncated_tool_panel()
                continue
            if message.startswith("/"):
                self._renderer.show_notice(
                    f"未知命令：{message}。输入 /help 查看可用命令。",
                )
                continue

            # 用户消息已在读取阶段显示，此处直接启动回复。
            self._active_reply_task = asyncio.create_task(
                self._stream_reply(message),
            )
            self._input.update_status(
                queue_size=message_queue.qsize(),
            )
            try:
                await self._active_reply_task
            except asyncio.CancelledError:
                if not self._reply_interrupt_requested:
                    raise
                self._renderer.show_notice("已中断当前回复。")
            finally:
                self._reply_interrupt_requested = False
                self._active_reply_task = None
                self._input.update_status(
                    queue_size=message_queue.qsize(),
                )

    async def _stream_reply(self, message: str) -> None:
        """消费一轮 AgentScope 事件，并确保动态渲染状态被清理。"""
        self._renderer.begin_reply()
        event_count = 0
        outcome = "completed"
        error: Exception | None = None
        try:
            async for event in self._service.reply_stream(message):
                self._renderer.handle(event)
                event_count += 1
                if event_count % 64 == 0:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            outcome = "interrupted"
            raise
        except Exception as exc:
            outcome = "error"
            error = exc
        finally:
            # 先收尾渲染并冲刷已生成内容，保证部分回复显示在错误面板之前。
            self._renderer.finish_reply(outcome=outcome)
        if error is not None:
            self._renderer.show_error(str(error))
