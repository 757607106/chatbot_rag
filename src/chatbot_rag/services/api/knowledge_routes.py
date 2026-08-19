"""多知识库管理 HTTP 路由。"""

from __future__ import annotations

from typing import Annotated

from agentscope.message import TextBlock
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from chatbot_rag.rag import (
    CatalogConflictError,
    CatalogError,
    CatalogNotFoundError,
    DocumentStatus,
    DocumentVersionRecord,
    KnowledgeJobRecord,
    RetrievalTraceItem,
)
from chatbot_rag.schemas import (
    ChunkMediaResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeChunkListResponse,
    KnowledgeChunkResponse,
    KnowledgeChunkUpdateRequest,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentVersionListResponse,
    KnowledgeDocumentVersionResponse,
    KnowledgeJobResponse,
    KnowledgeMutationResponse,
    RetrievalCandidateResponse,
    RetrievalTestRequest,
    RetrievalTestResponse,
)
from chatbot_rag.services import (
    InvalidDocumentUploadError,
    InvalidKnowledgeResourceError,
    KnowledgeBaseOverview,
    KnowledgeManagementCoordinator,
    KnowledgeManagementService,
    KnowledgeServiceError,
    ManagedChunk,
    ManagedDocument,
)
from chatbot_rag.services.api.management_auth import require_management_api_key


router = APIRouter(
    prefix="/api/v1/knowledge",
    tags=["knowledge-management"],
    dependencies=[Depends(require_management_api_key)],
)

_SCOPE_PATH = "/knowledge-bases/{knowledge_base_id}"


@router.get(
    "/knowledge-bases",
    response_model=KnowledgeBaseListResponse,
)
async def list_knowledge_bases(
    request: Request,
) -> KnowledgeBaseListResponse:
    """列出全部知识库。"""
    items = await _get_coordinator(request).list_knowledge_bases()
    return KnowledgeBaseListResponse(
        items=[_knowledge_base_response(item) for item in items],
    )


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    request: Request,
    body: KnowledgeBaseCreateRequest,
) -> KnowledgeBaseResponse:
    """创建一个使用独立物理 collection 的知识库。"""
    try:
        overview = await _get_coordinator(request).create_knowledge_base(
            name=body.name,
            description=body.description,
        )
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error
    except InvalidKnowledgeResourceError as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(error),
        ) from error
    return _knowledge_base_response(overview)


@router.delete(
    "/knowledge-bases/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_base(
    request: Request,
    knowledge_base_id: str,
) -> None:
    """删除一个已清空文档的非默认知识库及其物理资源。"""
    try:
        await _get_coordinator(request).delete_knowledge_base(
            knowledge_base_id,
        )
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error


@router.get(
    f"{_SCOPE_PATH}/documents",
    response_model=KnowledgeDocumentListResponse,
)
async def list_documents(
    request: Request,
    knowledge_base_id: str,
) -> KnowledgeDocumentListResponse:
    """列出指定知识库的文档与状态汇总。"""
    service = _get_service(request, knowledge_base_id)
    documents = await service.list_documents()
    items = [_document_response(item) for item in documents]
    processing_statuses = {
        DocumentStatus.QUEUED.value,
        DocumentStatus.PROCESSING.value,
        DocumentStatus.DELETING.value,
    }
    return KnowledgeDocumentListResponse(
        knowledge_base_id=service.knowledge_base_id,
        knowledge_base_name=service.knowledge_base_name,
        total_documents=len(items),
        total_chunks=sum(item.chunk_count for item in items),
        ready_documents=sum(item.status == "ready" for item in items),
        processing_documents=sum(
            item.status in processing_statuses for item in items
        ),
        failed_documents=sum(
            item.status in {"failed", "unsupported"} for item in items
        ),
        supported_extensions=[
            ".docx",
            ".md",
            ".markdown",
            ".pdf",
            ".pptx",
            ".txt",
            ".xls",
            ".xlsx",
        ],
        max_upload_bytes=service.max_upload_bytes,
        items=items,
    )


@router.get(
    f"{_SCOPE_PATH}/documents/{{document_id}}",
    response_model=KnowledgeDocumentResponse,
)
async def get_document(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
) -> KnowledgeDocumentResponse:
    """读取知识库内一个逻辑文档。"""
    try:
        return _document_response(
            await _get_service(
                request,
                knowledge_base_id,
            ).get_document(document_id),
        )
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post(
    f"{_SCOPE_PATH}/documents",
    response_model=KnowledgeMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    knowledge_base_id: str,
    file: Annotated[UploadFile, File()],
    replace: Annotated[bool, Query()] = False,
) -> KnowledgeMutationResponse:
    """上传文档，并在同知识库同名时要求显式替换。"""
    service = _get_service(request, knowledge_base_id)
    try:
        content = await file.read(service.max_upload_bytes + 1)
        document, job = await service.upload_document(
            filename=file.filename or "",
            media_type=file.content_type,
            content=content,
            replace=replace,
        )
        return await _mutation_response(service, document.document_id, job)
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error
    except InvalidDocumentUploadError as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(error),
        ) from error
    finally:
        await file.close()


@router.post(
    f"{_SCOPE_PATH}/documents/{{document_id}}/reindex",
    response_model=KnowledgeMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_document(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
) -> KnowledgeMutationResponse:
    """重新索引文档当前活动原文件版本。"""
    service = _get_service(request, knowledge_base_id)
    try:
        job = await service.reindex_document(document_id)
        return await _mutation_response(service, document_id, job)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except CatalogError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error


@router.delete(
    f"{_SCOPE_PATH}/documents/{{document_id}}",
    response_model=KnowledgeMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_document(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
) -> KnowledgeMutationResponse:
    """异步删除文档原文件、索引、媒体及内部版本。"""
    service = _get_service(request, knowledge_base_id)
    try:
        job = await service.delete_document(document_id)
        return await _mutation_response(service, document_id, job)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error


@router.get(
    f"{_SCOPE_PATH}/documents/{{document_id}}/chunks",
    response_model=KnowledgeChunkListResponse,
)
async def list_document_chunks(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> KnowledgeChunkListResponse:
    """分页读取当前活动索引的真实切片。"""
    try:
        page = await _get_service(
            request,
            knowledge_base_id,
        ).list_chunks(document_id, offset=offset, limit=limit)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except (KnowledgeServiceError, ValueError) as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error
    return KnowledgeChunkListResponse(
        document_id=document_id,
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        items=[_chunk_response(item) for item in page.items],
    )


@router.patch(
    f"{_SCOPE_PATH}/documents/{{document_id}}/chunks/{{chunk_index}}",
    response_model=KnowledgeChunkResponse,
)
async def update_document_chunk(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
    chunk_index: int,
    body: KnowledgeChunkUpdateRequest,
) -> KnowledgeChunkResponse:
    """重新嵌入并更新一个文本切片。"""
    try:
        chunk = await _get_service(
            request,
            knowledge_base_id,
        ).update_chunk(
            document_id,
            chunk_index,
            content=body.content,
            expected_content_hash=body.expected_content_hash,
        )
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error
    except (KnowledgeServiceError, ValueError) as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(error),
        ) from error
    return _chunk_response(chunk)


@router.get(
    f"{_SCOPE_PATH}/documents/{{document_id}}/versions",
    response_model=KnowledgeDocumentVersionListResponse,
)
async def list_document_versions(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
) -> KnowledgeDocumentVersionListResponse:
    """列出文档保留的全部原始文件版本。"""
    service = _get_service(request, knowledge_base_id)
    try:
        document = (await service.get_document(document_id)).document
        versions = await service.list_versions(document_id)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    total = len(versions)
    return KnowledgeDocumentVersionListResponse(
        document_id=document_id,
        items=[
            _version_response(
                version,
                version_number=total - index,
                active_version_id=document.active_version_id,
            )
            for index, version in enumerate(versions)
        ],
    )


@router.post(
    f"{_SCOPE_PATH}/documents/{{document_id}}/versions/{{version_id}}/rollback",
    response_model=KnowledgeMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rollback_document_version(
    request: Request,
    knowledge_base_id: str,
    document_id: str,
    version_id: str,
) -> KnowledgeMutationResponse:
    """异步把历史原文件版本重新索引为活动版本。"""
    service = _get_service(request, knowledge_base_id)
    try:
        job = await service.rollback_document(document_id, version_id)
        return await _mutation_response(service, document_id, job)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error
    except CatalogConflictError as error:
        raise _http_error(status.HTTP_409_CONFLICT, str(error)) from error


@router.get(
    f"{_SCOPE_PATH}/jobs/{{job_id}}",
    response_model=KnowledgeJobResponse,
)
async def get_job(
    request: Request,
    knowledge_base_id: str,
    job_id: str,
) -> KnowledgeJobResponse:
    """读取一个知识库内的持久化后台任务。"""
    try:
        return _job_response(
            await _get_service(
                request,
                knowledge_base_id,
            ).get_job(job_id),
        )
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post(
    f"{_SCOPE_PATH}/retrieval-tests",
    response_model=RetrievalTestResponse,
)
async def test_retrieval(
    request: Request,
    knowledge_base_id: str,
    body: RetrievalTestRequest,
) -> RetrievalTestResponse:
    """在指定知识库执行向量召回与重排序。"""
    try:
        trace = await _get_service(
            request,
            knowledge_base_id,
        ).test_retrieval(
            query=body.query,
            top_k=body.top_k,
            candidate_top_k=body.candidate_top_k,
            score_threshold=body.score_threshold,
        )
    except (KnowledgeServiceError, ValueError) as error:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(error),
        ) from error
    return RetrievalTestResponse(
        query=trace.query,
        rerank_status=trace.rerank_status,
        vector_elapsed_ms=trace.vector_elapsed_ms,
        rerank_elapsed_ms=trace.rerank_elapsed_ms,
        total_elapsed_ms=trace.total_elapsed_ms,
        vector_candidates=[
            _retrieval_candidate_response(item)
            for item in trace.vector_candidates
        ],
        final_results=[
            _retrieval_candidate_response(item)
            for item in trace.final_results
        ],
    )


def _get_coordinator(request: Request) -> KnowledgeManagementCoordinator:
    """从应用生命周期状态读取多知识库协调器。"""
    coordinator = getattr(request.app.state, "knowledge_coordinator", None)
    if not isinstance(coordinator, KnowledgeManagementCoordinator):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="知识库管理服务尚未就绪。",
        )
    return coordinator


def _get_service(
    request: Request,
    knowledge_base_id: str,
) -> KnowledgeManagementService:
    """解析指定知识库的服务。"""
    try:
        return _get_coordinator(request).get_service(knowledge_base_id)
    except CatalogNotFoundError as error:
        raise _http_error(status.HTTP_404_NOT_FOUND, str(error)) from error


async def _mutation_response(
    service: KnowledgeManagementService,
    document_id: str,
    job: KnowledgeJobRecord,
) -> KnowledgeMutationResponse:
    """读取最新文档状态并组成异步操作响应。"""
    return KnowledgeMutationResponse(
        document=_document_response(await service.get_document(document_id)),
        job=_job_response(job),
    )


def _knowledge_base_response(
    overview: KnowledgeBaseOverview,
) -> KnowledgeBaseResponse:
    """把知识库及统计转换为公开响应。"""
    record = overview.record
    return KnowledgeBaseResponse(
        knowledge_base_id=record.knowledge_base_id,
        name=record.name,
        description=record.description,
        is_default=record.is_default,
        total_documents=overview.total_documents,
        total_chunks=overview.total_chunks,
        processing_documents=overview.processing_documents,
        failed_documents=overview.failed_documents,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _document_response(managed: ManagedDocument) -> KnowledgeDocumentResponse:
    """把领域文档转换为严格的 HTTP 响应。"""
    document = managed.document
    return KnowledgeDocumentResponse(
        document_id=document.document_id,
        knowledge_base_id=document.knowledge_base_id,
        source_path=document.source_path,
        filename=document.filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        status=document.status.value,
        chunk_count=document.chunk_count,
        has_active_index=document.active_vector_document_id is not None,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_job=(
            None
            if managed.latest_job is None
            else _job_response(managed.latest_job)
        ),
    )


def _chunk_response(chunk: ManagedChunk) -> KnowledgeChunkResponse:
    """把管理切片转换为公开响应。"""
    return KnowledgeChunkResponse(
        chunk_index=chunk.chunk_index,
        total_chunks=chunk.total_chunks,
        source=chunk.source,
        content=chunk.content,
        content_hash=chunk.content_hash,
        is_manually_edited=chunk.is_manually_edited,
        metadata=dict(chunk.metadata),
        media=[
            ChunkMediaResponse(
                asset_id=media.asset_id,
                filename=media.filename,
                url=media.url,
            )
            for media in chunk.media
        ],
    )


def _version_response(
    version: DocumentVersionRecord,
    *,
    version_number: int,
    active_version_id: str | None,
) -> KnowledgeDocumentVersionResponse:
    """把内部版本路径隐藏后转换为公开响应。"""
    is_active = version.version_id == active_version_id
    return KnowledgeDocumentVersionResponse(
        version_id=version.version_id,
        document_id=version.document_id,
        version_number=version_number,
        content_hash=version.content_hash,
        size_bytes=version.size_bytes,
        status=version.status.value,
        is_active=is_active,
        can_rollback=not is_active and version.status.value == "inactive",
        created_at=version.created_at,
    )


def _job_response(job: KnowledgeJobRecord) -> KnowledgeJobResponse:
    """把内部任务记录转换为公开响应。"""
    return KnowledgeJobResponse(
        job_id=job.job_id,
        operation=job.operation.value,
        status=job.status.value,
        stage=job.stage,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _retrieval_candidate_response(
    item: RetrievalTraceItem,
) -> RetrievalCandidateResponse:
    """把诊断候选转换为不包含向量的公开数据。"""
    content = item.result.chunk.content
    text = (
        content.text
        if isinstance(content, TextBlock)
        else content.model_dump_json()
    )
    return RetrievalCandidateResponse(
        document_id=item.result.document_id,
        source=item.result.chunk.source,
        chunk_index=item.result.chunk.chunk_index,
        total_chunks=item.result.chunk.total_chunks,
        content=text,
        metadata=dict(item.result.chunk.metadata),
        vector_rank=item.vector_rank,
        vector_score=item.vector_score,
        final_rank=item.final_rank,
        rerank_score=item.rerank_score,
    )


def _http_error(status_code: int, detail: str) -> HTTPException:
    """创建统一的公开 HTTP 错误。"""
    return HTTPException(status_code=status_code, detail=detail)
