"""chatbot_rag 交互式终端入口。"""

from __future__ import annotations

import asyncio
import logging
import sys

from agentscope.rag import ApproxTokenChunker
from prompt_toolkit.patch_stdout import patch_stdout
from rich import box
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.text import Text

from chatbot_rag.agents import create_rag_agent
from chatbot_rag.cli.application import CliApplication
from chatbot_rag.cli.input_session import PromptInputSession
from chatbot_rag.cli.renderer import EventRenderer
from chatbot_rag.config import ConfigurationError, Settings
from chatbot_rag.rag import DocumentIngestor, open_knowledge_base
from chatbot_rag.services import ChatService


def main() -> None:
    """加载配置并运行交互式终端应用。"""
    console = Console()
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        _print_startup_error(console, str(error))
        raise SystemExit(2) from error

    try:
        asyncio.run(_run(settings, console))
    except KeyboardInterrupt:
        console.print("\n已退出。", style="dim")
    except Exception as error:
        _print_startup_error(console, str(error))
        raise SystemExit(1) from error


def _configure_logging(console: Console) -> None:
    """配置日志经由会话 Rich 控制台输出，避免与输入提示争夺终端。

    AgentScope 中间件（如 RAG）在检索失败时会输出 ERROR 级别日志，
    默认通过 stderr 直接写入终端，会破坏 prompt_toolkit 的输入区渲染。
    改用 RichHandler 将会话期日志纳入 patch_stdout 的代理控制台，
    由 prompt_toolkit 统一安排在提示区上方打印，并使用 Rich 格式化的
    traceback 替代原始堆栈，减少终端刷屏。
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(name)s: %(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=False,
                markup=False,
            ),
        ],
        force=True,
    )


async def _run(settings: Settings, console: Console) -> None:
    """装配知识库、智能体和 CLI，并维持资源生命周期。"""
    async with open_knowledge_base(settings) as knowledge_base:
        with console.status(
            "正在准备知识库...",
            spinner="dots",
            spinner_style="bold cyan",
        ) as status:
            summary = await DocumentIngestor(
                knowledge_base,
                ApproxTokenChunker(
                    chunk_size=settings.chunk_size,
                    overlap=settings.chunk_overlap,
                ),
            ).ingest_directory(
                settings.documents_path,
                progress_callback=lambda stage: status.update(stage.value),
            )

        agent = create_rag_agent(settings, knowledge_base)
        service = ChatService(agent)
        input_session = PromptInputSession(
            PromptInputSession.default_history_path(),
        )
        with patch_stdout(raw=True):
            # 输入提示运行期间，Rich 输出必须经过 StdoutProxy 协调，
            # 由 prompt_toolkit 统一安排在提示区上方打印。
            session_console = Console(file=sys.stdout)
            _configure_logging(session_console)
            renderer = EventRenderer(session_console)
            application = CliApplication(
                service,
                input_session,
                renderer,
                settings.agent_name,
                session_context=(
                    f"{settings.model_name} · "
                    f"{settings.knowledge_base_name} · "
                    f"{summary.indexed_documents + summary.skipped_documents} docs"
                ),
            )
            await application.run()


def _print_startup_error(console: Console, message: str) -> None:
    """显示启动阶段无法恢复的错误。"""
    console.print(
        Panel(
            Text(message),
            title="启动失败",
            border_style="red",
            box=box.ROUNDED,
        ),
    )


if __name__ == "__main__":
    main()
