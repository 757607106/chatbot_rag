"""多知识库注册表测试。"""

from pathlib import Path

import pytest

from chatbot_rag.rag import (
    CatalogConflictError,
    CatalogNotFoundError,
    KnowledgeBaseRegistry,
)


@pytest.mark.asyncio
async def test_registry_bootstraps_default_and_creates_knowledge_base(
    tmp_path: Path,
) -> None:
    """默认资源应兼容旧配置，新知识库应使用独立物理资源。"""
    registry = KnowledgeBaseRegistry(tmp_path / "catalog.sqlite3")
    await registry.initialize()
    default = await registry.ensure_default(
        knowledge_base_id="project_knowledge",
        knowledge_base_name="project_knowledge",
        description="默认资料",
        collection_name="project_knowledge",
        documents_path=tmp_path / "docs",
    )
    created = await registry.create_knowledge_base(
        name="产品资料",
        description="产品说明",
        documents_root=tmp_path / "knowledge",
    )

    assert default.is_default is True
    assert created.knowledge_base_id.startswith("kb_")
    assert created.collection_name == created.knowledge_base_id
    assert created.documents_path == tmp_path / "knowledge" / created.knowledge_base_id
    assert len(await registry.list_knowledge_bases()) == 2

    with pytest.raises(CatalogConflictError, match="同名知识库"):
        await registry.create_knowledge_base(
            name=" 产品资料 ",
            description="重复",
            documents_root=tmp_path / "knowledge",
        )


@pytest.mark.asyncio
async def test_registry_rejects_unknown_knowledge_base(tmp_path: Path) -> None:
    """读取未知知识库时应返回明确的领域错误。"""
    registry = KnowledgeBaseRegistry(tmp_path / "catalog.sqlite3")
    await registry.initialize()

    with pytest.raises(CatalogNotFoundError, match="知识库不存在"):
        await registry.get_knowledge_base("missing")
