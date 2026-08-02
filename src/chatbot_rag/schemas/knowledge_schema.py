"""知识库管理 HTTP 边界的数据结构。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeBaseCreateRequest(BaseModel):  # type: ignore[misc]
    """创建知识库请求。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class KnowledgeBaseResponse(BaseModel):  # type: ignore[misc]
    """一个知识库的公开信息与文档统计。"""

    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: str
    name: str
    description: str
    is_default: bool
    total_documents: int
    total_chunks: int
    processing_documents: int
    failed_documents: int
    created_at: str
    updated_at: str


class KnowledgeBaseListResponse(BaseModel):  # type: ignore[misc]
    """知识库列表。"""

    model_config = ConfigDict(extra="forbid")

    items: list[KnowledgeBaseResponse]


class KnowledgeJobResponse(BaseModel):  # type: ignore[misc]
    """后台任务的公开状态。"""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    operation: Literal["index", "reindex", "rollback", "delete"]
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    error_message: str | None
    created_at: str
    updated_at: str


class KnowledgeDocumentResponse(BaseModel):  # type: ignore[misc]
    """一个逻辑文档的公开管理状态。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    knowledge_base_id: str
    source_path: str
    filename: str
    media_type: str
    size_bytes: int
    status: Literal[
        "queued",
        "processing",
        "ready",
        "failed",
        "unsupported",
        "deleting",
    ]
    chunk_count: int
    has_active_index: bool
    error_message: str | None
    created_at: str
    updated_at: str
    latest_job: KnowledgeJobResponse | None


class KnowledgeDocumentListResponse(BaseModel):  # type: ignore[misc]
    """指定知识库的文档列表与汇总。"""

    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: str
    knowledge_base_name: str
    total_documents: int
    total_chunks: int
    ready_documents: int
    processing_documents: int
    failed_documents: int
    supported_extensions: list[str]
    max_upload_bytes: int
    items: list[KnowledgeDocumentResponse]


class KnowledgeMutationResponse(BaseModel):  # type: ignore[misc]
    """上传、替换、重建或删除操作的受理结果。"""

    model_config = ConfigDict(extra="forbid")

    document: KnowledgeDocumentResponse
    job: KnowledgeJobResponse


class ChunkMediaResponse(BaseModel):  # type: ignore[misc]
    """切片关联的浏览器安全图片。"""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    filename: str
    url: str


class KnowledgeChunkResponse(BaseModel):  # type: ignore[misc]
    """真正写入 Qdrant 的一个最终切片。"""

    model_config = ConfigDict(extra="forbid")

    chunk_index: int
    total_chunks: int
    source: str
    content: str
    content_hash: str
    is_manually_edited: bool
    metadata: dict[str, Any]
    media: list[ChunkMediaResponse]


class KnowledgeChunkListResponse(BaseModel):  # type: ignore[misc]
    """文档切片分页结果。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    total: int
    offset: int
    limit: int
    items: list[KnowledgeChunkResponse]


class KnowledgeChunkUpdateRequest(BaseModel):  # type: ignore[misc]
    """使用内容哈希保护的单切片编辑请求。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeDocumentVersionResponse(BaseModel):  # type: ignore[misc]
    """一个可审计、可回滚的原始文档版本。"""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    document_id: str
    version_number: int
    content_hash: str
    size_bytes: int
    status: Literal[
        "queued",
        "processing",
        "active",
        "inactive",
        "failed",
        "deleted",
    ]
    is_active: bool
    can_rollback: bool
    created_at: str


class KnowledgeDocumentVersionListResponse(BaseModel):  # type: ignore[misc]
    """一个逻辑文档的原始文件版本历史。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    items: list[KnowledgeDocumentVersionResponse]


class RetrievalTestRequest(BaseModel):  # type: ignore[misc]
    """直接召回诊断请求。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_top_k: int = Field(default=50, ge=1, le=500)
    score_threshold: float | None = None

    @model_validator(mode="after")
    def validate_candidate_count(self) -> RetrievalTestRequest:
        """确保向量候选数量不小于最终结果数量。"""
        if self.candidate_top_k < self.top_k:
            raise ValueError("candidate_top_k must not be less than top_k")
        return self


class RetrievalCandidateResponse(BaseModel):  # type: ignore[misc]
    """召回诊断中的候选切片及阶段排名。"""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    source: str
    chunk_index: int
    total_chunks: int
    content: str
    metadata: dict[str, Any]
    vector_rank: int
    vector_score: float
    final_rank: int | None
    rerank_score: float | None


class RetrievalTestResponse(BaseModel):  # type: ignore[misc]
    """一次向量召回和重排序的结构化诊断结果。"""

    model_config = ConfigDict(extra="forbid")

    query: str
    rerank_status: Literal["succeeded", "skipped", "fallback"]
    vector_elapsed_ms: float
    rerank_elapsed_ms: float
    total_elapsed_ms: float
    vector_candidates: list[RetrievalCandidateResponse]
    final_results: list[RetrievalCandidateResponse]
