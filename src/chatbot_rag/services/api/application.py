"""FastAPI 应用装配与资源生命周期。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentscope.rag import ApproxTokenChunker
from fastapi import FastAPI

from chatbot_rag.agents import create_rag_agent
from chatbot_rag.config import Settings
from chatbot_rag.rag import DocumentIngestor, open_knowledge_base
from chatbot_rag.services import ChatService
from chatbot_rag.services.api.chat_routes import router as chat_router


def create_app(chat_service: ChatService | None = None) -> FastAPI:
    """创建 HTTP 应用。

    Args:
        chat_service: 隔离测试可注入的聊天服务。

    Returns:
        完成配置的 FastAPI 应用。
    """
    lifespan = None if chat_service is not None else _production_lifespan
    app = FastAPI(
        title="chatbot_rag API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.chat_lock = asyncio.Lock()
    if chat_service is not None:
        app.state.chat_service = chat_service
    app.include_router(chat_router)
    return app


@asynccontextmanager
async def _production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """在 HTTP 应用生命周期内持有知识库与聊天服务。"""
    settings = Settings.from_env()
    async with open_knowledge_base(settings) as knowledge_base:
        await DocumentIngestor(
            knowledge_base,
            ApproxTokenChunker(
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            ),
        ).ingest_directory(settings.documents_path)
        app.state.chat_service = ChatService(
            create_rag_agent(settings, knowledge_base),
        )
        yield
