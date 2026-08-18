"""FastAPI 应用装配与资源生命周期。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentscope.agent import Agent
from fastapi import FastAPI

from chatbot_rag.agents import create_rag_agent
from chatbot_rag.config import Settings
from chatbot_rag.models import create_asr_model, create_tts_model
from chatbot_rag.rag import (
    KnowledgeBaseRegistry,
    MediaAssetStore,
    open_knowledge_base_runtime,
)
from chatbot_rag.services import (
    ChatService,
    KnowledgeManagementCoordinator,
    SpeechRecognitionService,
    SpeechSynthesisService,
)
from chatbot_rag.services.api.chat_routes import router as chat_router
from chatbot_rag.services.api.knowledge_routes import router as knowledge_router
from chatbot_rag.services.api.media_routes import router as media_router
from chatbot_rag.services.api.speech_routes import router as speech_router


def create_app(
    chat_service: ChatService | None = None,
    media_store: MediaAssetStore | None = None,
    knowledge_coordinator: KnowledgeManagementCoordinator | None = None,
) -> FastAPI:
    """创建 HTTP 应用。

    Args:
        chat_service: 隔离测试可注入的聊天服务。
        media_store: 隔离测试可注入的图片资产仓库。
        knowledge_coordinator: 隔离测试可注入的多知识库协调器。

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
    if chat_service is not None:
        app.state.chat_service = chat_service
    app.include_router(chat_router)
    app.include_router(media_router)
    app.include_router(knowledge_router)
    app.include_router(speech_router)
    return app


@asynccontextmanager
async def _production_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """在 HTTP 应用生命周期内持有知识库与聊天服务。"""
    settings = Settings.from_env()
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
            """为每次请求创建不共享对话状态的智能体。"""
            return await create_rag_agent(
                settings,
                coordinator.default_service().knowledge_base,
            )

        app.state.chat_service = ChatService(create_request_agent)
        # TTS 模型每次调用独立创建合成器，无需额外的连接生命周期管理。
        app.state.speech_service = SpeechSynthesisService(
            create_tts_model(settings),
        )
        app.state.speech_recognition_service = SpeechRecognitionService(
            create_asr_model(settings),
        )
        try:
            yield
        finally:
            await coordinator.stop()
