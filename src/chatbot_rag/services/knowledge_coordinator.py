"""多知识库管理服务协调器。"""

from __future__ import annotations

from dataclasses import dataclass

from agentscope.rag import ApproxTokenChunker

from chatbot_rag.config import Settings
from chatbot_rag.rag import (
    CatalogNotFoundError,
    ContextPreservingChunker,
    DocumentIngestor,
    KnowledgeBaseRecord,
    KnowledgeBaseRegistry,
    KnowledgeBaseRuntimeFactory,
    KnowledgeCatalog,
    MediaAssetStore,
    QdrantChunkReader,
)
from chatbot_rag.services.knowledge_service import (
    KnowledgeManagementService,
    KnowledgeServiceError,
)


class InvalidKnowledgeResourceError(KnowledgeServiceError):
    """知识库名称或说明不符合控制面约束。"""


@dataclass(frozen=True, slots=True)
class KnowledgeBaseOverview:
    """知识库定义及其当前文档统计。"""

    record: KnowledgeBaseRecord
    total_documents: int
    total_chunks: int
    processing_documents: int
    failed_documents: int


class KnowledgeManagementCoordinator:
    """维护知识库注册表以及每个知识库的独立后台服务。"""

    def __init__(
        self,
        *,
        settings: Settings,
        registry: KnowledgeBaseRegistry,
        runtime_factory: KnowledgeBaseRuntimeFactory,
        media_store: MediaAssetStore,
    ) -> None:
        """绑定共享配置、注册表、Qdrant 生命周期和图片仓库。"""
        self._settings = settings
        self._registry = registry
        self._runtime_factory = runtime_factory
        self._media_store = media_store
        self._services: dict[str, KnowledgeManagementService] = {}

    async def start(self) -> None:
        """初始化注册表并恢复全部知识库的持久化任务。"""
        await self._registry.initialize()
        await self._registry.ensure_default(
            knowledge_base_id=self._settings.knowledge_base_name,
            knowledge_base_name=self._settings.knowledge_base_name,
            description="用于回答项目资料相关问题的默认知识库。",
            collection_name=self._settings.knowledge_collection,
            documents_path=self._settings.documents_path,
        )
        for record in await self._registry.list_knowledge_bases():
            await self._start_service(record)

    async def stop(self) -> None:
        """依次等待所有知识库任务完成并停止工作协程。"""
        for service in reversed(list(self._services.values())):
            await service.stop()
        self._services.clear()

    async def list_knowledge_bases(self) -> list[KnowledgeBaseOverview]:
        """列出全部知识库及其轻量文档统计。"""
        overviews: list[KnowledgeBaseOverview] = []
        for record in await self._registry.list_knowledge_bases():
            service = self._services.get(record.knowledge_base_id)
            if service is None:
                service = await self._start_service(record)
            documents = await service.list_documents()
            overviews.append(
                KnowledgeBaseOverview(
                    record=record,
                    total_documents=len(documents),
                    total_chunks=sum(
                        item.document.chunk_count for item in documents
                    ),
                    processing_documents=sum(
                        item.document.status.value
                        in {"queued", "processing", "deleting"}
                        for item in documents
                    ),
                    failed_documents=sum(
                        item.document.status.value in {"failed", "unsupported"}
                        for item in documents
                    ),
                ),
            )
        return overviews

    async def create_knowledge_base(
        self,
        *,
        name: str,
        description: str,
    ) -> KnowledgeBaseOverview:
        """创建具备独立目录、collection 和后台任务队列的知识库。"""
        record = await self._registry.create_knowledge_base(
            name=_validate_name(name, "知识库名称"),
            description=_validate_description(description),
            documents_root=self._settings.knowledge_documents_root_path,
        )
        await self._start_service(record)
        return KnowledgeBaseOverview(
            record=record,
            total_documents=0,
            total_chunks=0,
            processing_documents=0,
            failed_documents=0,
        )

    async def get_record(
        self,
        knowledge_base_id: str,
    ) -> KnowledgeBaseRecord:
        """读取知识库定义。"""
        return await self._registry.get_knowledge_base(knowledge_base_id)

    def get_service(
        self,
        knowledge_base_id: str,
    ) -> KnowledgeManagementService:
        """返回已启动的知识库服务。"""
        service = self._services.get(knowledge_base_id)
        if service is None:
            raise CatalogNotFoundError("知识库不存在。")
        return service

    def default_service(self) -> KnowledgeManagementService:
        """返回继续供现有聊天链路使用的默认知识库服务。"""
        return self.get_service(self._settings.knowledge_base_name)

    async def _start_service(
        self,
        record: KnowledgeBaseRecord,
    ) -> KnowledgeManagementService:
        """创建并启动一个知识库的独立控制面服务。"""
        existing = self._services.get(record.knowledge_base_id)
        if existing is not None:
            return existing
        knowledge_base = self._runtime_factory.create(
            name=record.name,
            description=record.description,
            collection=record.collection_name,
        )
        versions_path = (
            self._settings.document_versions_path
            if record.is_default
            else self._settings.document_versions_path
            / record.knowledge_base_id
        )
        service = KnowledgeManagementService(
            knowledge_base=knowledge_base,
            ingestor=DocumentIngestor(
                knowledge_base,
                ContextPreservingChunker(
                    ApproxTokenChunker(
                        chunk_size=self._settings.chunk_size,
                        overlap=self._settings.chunk_overlap,
                    ),
                ),
                media_store=self._media_store,
            ),
            catalog=KnowledgeCatalog(
                self._settings.knowledge_catalog_path,
                record.knowledge_base_id,
            ),
            chunk_reader=QdrantChunkReader(knowledge_base),
            media_store=self._media_store,
            knowledge_base_id=record.knowledge_base_id,
            knowledge_base_name=record.name,
            media_document_prefix=(
                None if record.is_default else record.knowledge_base_id
            ),
            documents_path=record.documents_path,
            versions_path=versions_path,
            max_upload_bytes=self._settings.max_upload_bytes,
        )
        await service.start()
        self._services[record.knowledge_base_id] = service
        return service


def _validate_name(value: str, field_name: str) -> str:
    """校验用户可见资源名称。"""
    normalized = " ".join(value.split())
    if not normalized:
        raise InvalidKnowledgeResourceError(f"{field_name}不能为空。")
    if len(normalized) > 80:
        raise InvalidKnowledgeResourceError(f"{field_name}不能超过 80 个字符。")
    return normalized


def _validate_description(value: str) -> str:
    """校验供管理员和检索工具阅读的知识库说明。"""
    normalized = value.strip()
    if len(normalized) > 500:
        raise InvalidKnowledgeResourceError("说明不能超过 500 个字符。")
    return normalized
