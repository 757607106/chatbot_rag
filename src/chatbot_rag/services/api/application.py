"""FastAPI 应用装配与资源生命周期。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentscope.agent import Agent
from agentscope.tool import Toolkit
from fastapi import FastAPI

from chatbot_rag.agents import create_chat_agent, create_knowledge_middleware
from chatbot_rag.config import Settings
from chatbot_rag.models import DashScopeRealtimeVoiceConnectionFactory
from chatbot_rag.rag import (
    KnowledgeBaseRegistry,
    MediaAssetStore,
    open_knowledge_base_runtime,
)
from chatbot_rag.services import (
    ChatService,
    KnowledgeManagementCoordinator,
    RealtimeVoiceService,
)
from chatbot_rag.services.api.chat_routes import router as chat_router
from chatbot_rag.services.api.knowledge_routes import router as knowledge_router
from chatbot_rag.services.api.media_routes import router as media_router
from chatbot_rag.services.api.voice_routes import router as voice_router
from chatbot_rag.tools import create_mcp_clients


def create_app(
    chat_service: ChatService | None = None,
    media_store: MediaAssetStore | None = None,
    knowledge_coordinator: KnowledgeManagementCoordinator | None = None,
    realtime_voice_service: RealtimeVoiceService | None = None,
    management_api_key: str | None = None,
) -> FastAPI:
    """创建 HTTP 应用。

    Args:
        chat_service: 隔离测试可注入的聊天服务。
        media_store: 隔离测试可注入的图片资产仓库。
        knowledge_coordinator: 隔离测试可注入的多知识库协调器。
        realtime_voice_service: 隔离测试可注入的实时语音服务。
        management_api_key: 隔离测试可注入的管理 API 共享密钥。

    Returns:
        完成配置的 FastAPI 应用。
    """
    lifespan = None if chat_service is not None else _production_lifespan
    app = FastAPI(
        title="chatbot_rag API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.media_store = media_store
    app.state.knowledge_coordinator = knowledge_coordinator
    app.state.realtime_voice_service = realtime_voice_service
    app.state.management_api_key = management_api_key
    if chat_service is not None:
        app.state.chat_service = chat_service
    app.include_router(chat_router)
    app.include_router(media_router)
    app.include_router(knowledge_router)
    app.include_router(voice_router)
    return app


@asynccontextmanager
async def _production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """在 HTTP 应用生命周期内持有知识库与聊天服务。"""
    settings = Settings.from_env()
    # debug 模式下把 chatbot_rag 包日志降到 DEBUG，输出检索、流式处理等调试细节；
    # 默认保持 INFO，与 uvicorn 根日志级别一致。
    logging.getLogger("chatbot_rag").setLevel(
        logging.DEBUG if settings.debug else logging.INFO,
    )
    app.state.management_api_key = settings.management_api_key
    media_store = MediaAssetStore(
        settings.media_path,
        allowed_remote_hosts=settings.remote_image_hosts,
    )
    app.state.media_store = media_store
    async with open_knowledge_base_runtime(settings) as runtime_factory:
        coordinator = KnowledgeManagementCoordinator(
            settings=settings,
            registry=KnowledgeBaseRegistry(settings.knowledge_catalog_path),
            runtime_factory=runtime_factory,
            media_store=media_store,
        )
        app.state.knowledge_coordinator = coordinator
        await coordinator.start()

        async def create_request_agent() -> Agent:
            """为每次请求创建绑定全部知识库的独立智能体。"""
            return await create_chat_agent(
                settings,
                await coordinator.chat_knowledge_bases(),
            )

        app.state.chat_service = ChatService(create_request_agent)
        voice_middleware = create_knowledge_middleware(
            settings,
            await coordinator.chat_knowledge_bases(),
        )
        app.state.realtime_voice_service = RealtimeVoiceService(
            connection_factory=DashScopeRealtimeVoiceConnectionFactory(
                api_key=settings.dashscope_api_key,
                base_url=settings.realtime_voice_base_url,
                model_name=settings.realtime_voice_model_name,
            ),
            toolkit=Toolkit(
                tools=await voice_middleware.list_tools(),
                mcps=create_mcp_clients(settings.mcp_servers),
            ),
            voice_name=settings.realtime_voice_name,
            allowed_origins=settings.realtime_voice_allowed_origins,
        )
        try:
            yield
        finally:
            await coordinator.stop()
