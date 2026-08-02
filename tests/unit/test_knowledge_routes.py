"""知识库管理 HTTP 路由测试。"""

from pathlib import Path
from typing import cast

import httpx
import pytest
from agentscope.rag import KnowledgeBase

from chatbot_rag.rag import (
    DocumentIngestor,
    KnowledgeCatalog,
    MediaAssetStore,
    QdrantChunkReader,
)
from chatbot_rag.services import (
    ChatService,
    KnowledgeManagementCoordinator,
    KnowledgeManagementService,
)
from chatbot_rag.services.api import create_app


class EmptyKnowledgeBase:
    """为列表路由提供名称的空知识库。"""

    name = "project_knowledge"


@pytest.mark.asyncio
async def test_knowledge_routes_accept_direct_requests_and_upload(
    tmp_path: Path,
) -> None:
    """管理接口应直接受理列表、上传和诊断请求。"""
    catalog = KnowledgeCatalog(tmp_path / "catalog.sqlite3", "project_knowledge")
    await catalog.initialize()
    service = KnowledgeManagementService(
        knowledge_base=cast(KnowledgeBase, EmptyKnowledgeBase()),
        ingestor=cast(DocumentIngestor, object()),
        catalog=catalog,
        chunk_reader=cast(QdrantChunkReader, object()),
        media_store=MediaAssetStore(tmp_path / "media", ()),
        knowledge_base_id="project_knowledge",
        knowledge_base_name="project_knowledge",
        media_document_prefix=None,
        documents_path=tmp_path / "documents",
        versions_path=tmp_path / "versions",
        max_upload_bytes=1024,
    )
    coordinator = object.__new__(KnowledgeManagementCoordinator)
    coordinator._services = {"project_knowledge": service}
    app = create_app(
        chat_service=cast(ChatService, object()),
        knowledge_coordinator=coordinator,
    )
    transport = httpx.ASGITransport(app=app)
    scope_path = "/api/v1/knowledge/knowledge-bases/project_knowledge"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        documents = await client.get(f"{scope_path}/documents")
        upload = await client.post(
            f"{scope_path}/documents",
            files={"file": ("guide.md", b"knowledge", "text/markdown")},
        )
        conflict = await client.post(
            f"{scope_path}/documents",
            files={"file": ("guide.md", b"new", "text/markdown")},
        )
        document_id = upload.json()["document"]["document_id"]
        job_id = upload.json()["job"]["job_id"]
        document_detail = await client.get(
            f"{scope_path}/documents/{document_id}",
        )
        job_detail = await client.get(
            f"{scope_path}/jobs/{job_id}",
        )
        missing = await client.get(
            f"{scope_path}/documents/missing",
        )
        retrieval = await client.post(
            f"{scope_path}/retrieval-tests",
            json={"query": "测试问题", "top_k": 5, "candidate_top_k": 50},
        )
        unsupported = await client.post(
            f"{scope_path}/documents",
            files={"file": ("legacy.doc", b"legacy", "application/msword")},
        )

    assert documents.status_code == 200
    assert documents.json()["knowledge_base_id"] == "project_knowledge"
    assert upload.status_code == 202
    assert upload.json()["document"]["status"] == "queued"
    assert conflict.status_code == 409
    assert document_detail.status_code == 200
    assert job_detail.status_code == 200
    assert missing.status_code == 404
    assert retrieval.status_code == 422
    assert unsupported.status_code == 422
