"""章节上下文保留切块器测试。"""

from __future__ import annotations

import pytest
from agentscope.message import TextBlock
from agentscope.rag import ApproxTokenChunker, Section

from chatbot_rag.rag.contextual_chunker import (
    ContextPreservingChunker,
    RETRIEVAL_CONTEXT_KEY,
)


@pytest.mark.asyncio
async def test_chunker_repeats_context_for_every_split_chunk() -> None:
    """长章节被拆成多个块后，每一块都应携带完整标题路径。"""
    context = "# 打印手册\n## 本地打印模式\n### 设置打印模板"
    chunker = ContextPreservingChunker(
        ApproxTokenChunker(chunk_size=32, overlap=4),
    )

    chunks = await chunker.chunk(
        [
            Section(
                content=TextBlock(
                    text="在打印管理器点击模板编辑。" * 20,
                ),
                source="print-guide.md",
                metadata={RETRIEVAL_CONTEXT_KEY: context},
            ),
        ],
    )

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(
        range(len(chunks)),
    )
    assert all(chunk.total_chunks == len(chunks) for chunk in chunks)
    for chunk in chunks:
        assert isinstance(chunk.content, TextBlock)
        assert chunk.content.text.startswith(
            f"文档来源：print-guide.md\n{context}\n\n",
        )


@pytest.mark.asyncio
async def test_chunker_adds_source_context_without_heading_context() -> None:
    """没有标题的 Word 等文本块仍应携带真实文档来源。"""
    chunker = ContextPreservingChunker(
        ApproxTokenChunker(chunk_size=32, overlap=4),
    )

    chunks = await chunker.chunk(
        [
            Section(
                content=TextBlock(text="普通文档内容"),
                source="plain.txt",
                metadata={},
            ),
        ],
    )

    assert len(chunks) == 1
    assert isinstance(chunks[0].content, TextBlock)
    assert chunks[0].content.text == "文档来源：plain.txt\n\n普通文档内容"


@pytest.mark.asyncio
async def test_chunker_adds_page_context_for_paginated_document() -> None:
    """PDF 等分页文档的每个块应保留来源与页码。"""
    chunker = ContextPreservingChunker(
        ApproxTokenChunker(chunk_size=32, overlap=4),
    )

    chunks = await chunker.chunk(
        [
            Section(
                content=TextBlock(text="分页文档内容"),
                source="manual.pdf",
                metadata={"page": 7},
            ),
        ],
    )

    assert len(chunks) == 1
    assert isinstance(chunks[0].content, TextBlock)
    assert chunks[0].content.text == (
        "文档来源：manual.pdf\n页码：7\n\n分页文档内容"
    )
