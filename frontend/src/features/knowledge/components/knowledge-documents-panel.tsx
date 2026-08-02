"use client";

import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FileTextIcon,
  HistoryIcon,
  LoaderCircleIcon,
  PencilIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteKnowledgeDocument,
  listDocumentVersions,
  listKnowledgeChunks,
  reindexKnowledgeDocument,
  rollbackDocumentVersion,
  updateKnowledgeChunk,
} from "@/features/knowledge/api/knowledge-api";
import type {
  DocumentStatus,
  KnowledgeChunk,
  KnowledgeChunkList,
  KnowledgeDocument,
  KnowledgeDocumentList,
  KnowledgeDocumentVersionList,
  KnowledgeScope,
} from "@/features/knowledge/schemas/knowledge";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<DocumentStatus, string> = {
  queued: "等待处理",
  processing: "处理中",
  ready: "可用",
  failed: "处理失败",
  unsupported: "格式不支持",
  deleting: "删除中",
};

const PROCESSING_STATUSES = new Set<DocumentStatus>(["queued", "processing", "deleting"]);
const CHUNK_PAGE_SIZE = 10;

export function KnowledgeDocumentsPanel({
  scope,
  snapshot,
  search,
  onSearchChange,
  onChanged,
  onError,
}: {
  scope: KnowledgeScope;
  snapshot: KnowledgeDocumentList | null;
  search: string;
  onSearchChange: (value: string) => void;
  onChanged: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [chunkPage, setChunkPage] = useState<KnowledgeChunkList | null>(null);
  const [versions, setVersions] = useState<KnowledgeDocumentVersionList | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyDocumentId, setBusyDocumentId] = useState<string | null>(null);

  useEffect(() => {
    setSelectedDocumentId(null);
    setChunkPage(null);
    setVersions(null);
  }, [scope.knowledgeBaseId]);

  const selectedDocument = useMemo(
    () => snapshot?.items.find((item) => item.document_id === selectedDocumentId) ?? null,
    [selectedDocumentId, snapshot],
  );
  const filteredDocuments = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    if (!query) return snapshot?.items ?? [];
    return (snapshot?.items ?? []).filter((document) =>
      document.filename.toLocaleLowerCase("zh-CN").includes(query),
    );
  }, [search, snapshot]);

  const loadDetail = useCallback(
    async (document: KnowledgeDocument, offset = 0) => {
      setDetailLoading(true);
      try {
        const [nextVersions, nextChunks] = await Promise.all([
          listDocumentVersions(scope, document.document_id),
          document.has_active_index
            ? listKnowledgeChunks(scope, document.document_id, offset, CHUNK_PAGE_SIZE)
            : Promise.resolve(null),
        ]);
        setVersions(nextVersions);
        setChunkPage(nextChunks);
      } catch (caught) {
        onError(caught);
      } finally {
        setDetailLoading(false);
      }
    },
    [onError, scope],
  );

  const selectDocument = (document: KnowledgeDocument) => {
    setSelectedDocumentId(document.document_id);
    setChunkPage(null);
    setVersions(null);
    void loadDetail(document);
  };

  const mutateDocument = async (document: KnowledgeDocument, operation: () => Promise<unknown>) => {
    setBusyDocumentId(document.document_id);
    try {
      await operation();
      await onChanged();
      if (selectedDocumentId === document.document_id) await loadDetail(document);
      return true;
    } catch (caught) {
      onError(caught);
      return false;
    } finally {
      setBusyDocumentId(null);
    }
  };

  const handleDelete = (document: KnowledgeDocument) => {
    if (
      !window.confirm(`确定删除“${document.filename}”吗？原文件、全部版本、索引和图片都会被删除。`)
    ) {
      return;
    }
    void mutateDocument(document, () => deleteKnowledgeDocument(scope, document.document_id)).then(
      (succeeded) => {
        if (!succeeded) return;
        setSelectedDocumentId(null);
        setChunkPage(null);
        setVersions(null);
      },
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 border-b border-black/10 pb-5 text-sm sm:flex sm:items-center dark:border-white/10">
        <Metric label="文档" value={snapshot?.total_documents ?? 0} />
        <Metric label="切片" value={snapshot?.total_chunks ?? 0} />
        <Metric label="处理中" value={snapshot?.processing_documents ?? 0} />
        <Metric label="异常" value={snapshot?.failed_documents ?? 0} />
        <label className="relative col-span-2 sm:ml-auto sm:w-64">
          <span className="sr-only">搜索文档</span>
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[#888]" />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="搜索文档名称"
            className="h-9 w-full rounded-lg border border-black/10 bg-[#f7f7f7] pr-3 pl-9 text-sm outline-none focus:border-black/30 dark:border-white/10 dark:bg-[#1c1c1c] dark:focus:border-white/30"
          />
        </label>
      </div>

      <div
        className={cn(
          "grid min-h-0 gap-5",
          selectedDocument && "xl:grid-cols-[minmax(0,1fr)_480px]",
        )}
      >
        <div className="overflow-hidden rounded-xl border border-black/10 dark:border-white/10">
          <div className="hidden grid-cols-[minmax(220px,2fr)_120px_80px_130px_180px] gap-4 bg-[#f7f7f7] px-4 py-2.5 text-xs text-[#777] md:grid dark:bg-[#171717] dark:text-[#aaa]">
            <span>文档</span>
            <span>状态</span>
            <span>切片</span>
            <span>更新时间</span>
            <span className="text-right">操作</span>
          </div>
          {filteredDocuments.length === 0 ? (
            <EmptyDocuments />
          ) : (
            filteredDocuments.map((document) => (
              <DocumentRow
                key={document.document_id}
                document={document}
                selected={selectedDocument?.document_id === document.document_id}
                busy={busyDocumentId === document.document_id}
                onSelect={() => selectDocument(document)}
                onReindex={() =>
                  void mutateDocument(document, () =>
                    reindexKnowledgeDocument(scope, document.document_id),
                  )
                }
                onDelete={() => handleDelete(document)}
              />
            ))
          )}
        </div>

        {selectedDocument !== null && (
          <DocumentDetail
            scope={scope}
            document={selectedDocument}
            page={chunkPage}
            versions={versions}
            loading={detailLoading}
            busy={busyDocumentId === selectedDocument.document_id}
            onClose={() => {
              setSelectedDocumentId(null);
              setChunkPage(null);
              setVersions(null);
            }}
            onPageChange={(offset) => void loadDetail(selectedDocument, offset)}
            onChunkChanged={async () => {
              await loadDetail(selectedDocument, chunkPage?.offset ?? 0);
              await onChanged();
            }}
            onRollback={(versionId) => {
              if (!window.confirm("确定回滚到该原文件版本吗？当前手工切片编辑将被新的索引替换。")) {
                return;
              }
              void mutateDocument(selectedDocument, () =>
                rollbackDocumentVersion(scope, selectedDocument.document_id, versionId),
              );
            }}
            onError={onError}
          />
        )}
      </div>
    </div>
  );
}

function EmptyDocuments() {
  return (
    <div className="grid min-h-56 place-items-center px-5 text-center">
      <div>
        <FileTextIcon className="mx-auto size-7 text-[#999]" />
        <p className="mt-3 text-sm font-medium">没有找到文档</p>
        <p className="mt-1 text-xs text-[#777] dark:text-[#aaa]">
          上传支持的文件，或调整搜索条件。
        </p>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <strong className="text-base font-medium tabular-nums">{value}</strong>
      <span className="text-xs text-[#777] dark:text-[#aaa]">{label}</span>
    </div>
  );
}

function DocumentRow({
  document,
  selected,
  busy,
  onSelect,
  onReindex,
  onDelete,
}: {
  document: KnowledgeDocument;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onReindex: () => void;
  onDelete: () => void;
}) {
  const processing = PROCESSING_STATUSES.has(document.status);
  return (
    <div
      className={cn(
        "grid gap-3 border-t border-black/[0.07] px-4 py-3 first:border-t-0 md:grid-cols-[minmax(220px,2fr)_120px_80px_130px_180px] md:items-center md:gap-4 dark:border-white/10",
        selected && "bg-black/[0.035] dark:bg-white/[0.06]",
      )}
    >
      <button type="button" onClick={onSelect} className="min-w-0 text-left">
        <span className="block truncate text-sm font-medium">{document.filename}</span>
        <span className="mt-1 block truncate font-mono text-[11px] text-[#777] dark:text-[#999]">
          {formatBytes(document.size_bytes)} · {document.source_path}
        </span>
      </button>
      <div>
        <StatusBadge status={document.status} />
        {processing && document.latest_job !== null && (
          <span className="mt-1 block text-[11px] text-[#777] dark:text-[#999]">
            {document.latest_job.stage}
          </span>
        )}
      </div>
      <span className="hidden text-sm tabular-nums md:block">{document.chunk_count || "—"}</span>
      <span className="hidden text-xs text-[#666] md:block dark:text-[#aaa]">
        {formatDate(document.updated_at)}
      </span>
      <div className="flex items-center gap-1 md:justify-end">
        <button
          type="button"
          onClick={onSelect}
          className="h-8 rounded-lg px-2.5 text-xs hover:bg-black/[0.06] dark:hover:bg-white/10"
        >
          切片与版本
        </button>
        <button
          type="button"
          onClick={onReindex}
          disabled={busy || processing || !document.has_active_index}
          aria-label={`重新索引 ${document.filename}`}
          title="重新索引"
          className="grid size-8 place-items-center rounded-lg hover:bg-black/[0.06] disabled:opacity-35 dark:hover:bg-white/10"
        >
          <RefreshCwIcon className={cn("size-3.5", busy && "animate-spin")} />
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy || processing}
          aria-label={`删除 ${document.filename}`}
          title="删除文档"
          className="grid size-8 place-items-center rounded-lg text-red-600 hover:bg-red-50 disabled:opacity-35 dark:text-red-400 dark:hover:bg-red-950/40"
        >
          <Trash2Icon className="size-3.5" />
        </button>
      </div>
      {document.error_message !== null && (
        <p className="text-xs text-red-600 md:col-span-5 dark:text-red-300">
          {document.error_message}
          {document.has_active_index && "（旧索引仍可使用）"}
        </p>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  const style =
    status === "ready"
      ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
      : status === "failed" || status === "unsupported"
        ? "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300"
        : "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300";
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px]", style)}
    >
      {PROCESSING_STATUSES.has(status) && (
        <span className="size-1.5 animate-pulse rounded-full bg-current" />
      )}
      {STATUS_LABELS[status]}
    </span>
  );
}

function DocumentDetail({
  scope,
  document,
  page,
  versions,
  loading,
  busy,
  onClose,
  onPageChange,
  onChunkChanged,
  onRollback,
  onError,
}: {
  scope: KnowledgeScope;
  document: KnowledgeDocument;
  page: KnowledgeChunkList | null;
  versions: KnowledgeDocumentVersionList | null;
  loading: boolean;
  busy: boolean;
  onClose: () => void;
  onPageChange: (offset: number) => void;
  onChunkChanged: () => Promise<void>;
  onRollback: (versionId: string) => void;
  onError: (error: unknown) => void;
}) {
  return (
    <aside className="min-w-0 rounded-xl border border-black/10 bg-[#fafafa] dark:border-white/10 dark:bg-[#151515]">
      <div className="flex items-start gap-3 border-b border-black/10 px-4 py-4 dark:border-white/10">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-medium">{document.filename}</h2>
          <p className="mt-1 text-xs text-[#777] dark:text-[#aaa]">
            {document.chunk_count} 个切片 · {versions?.items.length ?? 0} 个原文件版本
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭文档详情"
          className="grid size-8 place-items-center rounded-lg hover:bg-black/[0.06] dark:hover:bg-white/10"
        >
          <XIcon className="size-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-[#777] dark:text-[#aaa]">
          <LoaderCircleIcon className="size-4 animate-spin" />
          正在读取切片与版本…
        </div>
      ) : (
        <>
          <VersionHistory versions={versions} busy={busy} onRollback={onRollback} />
          <div className="border-t border-black/10 dark:border-white/10">
            <div className="flex items-center gap-2 px-4 py-3">
              <PencilIcon className="size-3.5 text-[#777]" />
              <h3 className="text-xs font-medium">活动索引切片</h3>
              <span className="ml-auto text-[11px] text-[#777] dark:text-[#aaa]">
                保存后立即重新嵌入
              </span>
            </div>
            {page === null ? (
              <div className="px-4 pb-5 text-sm text-[#777] dark:text-[#aaa]">
                当前没有可浏览的活动切片。
              </div>
            ) : (
              <>
                <div className="space-y-3 px-3 pb-3">
                  {page.items.map((chunk) => (
                    <ChunkCard
                      key={`${chunk.chunk_index}:${chunk.content_hash}`}
                      scope={scope}
                      documentId={document.document_id}
                      chunk={chunk}
                      onChanged={onChunkChanged}
                      onError={onError}
                    />
                  ))}
                </div>
                <ChunkPagination page={page} onPageChange={onPageChange} />
              </>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

function VersionHistory({
  versions,
  busy,
  onRollback,
}: {
  versions: KnowledgeDocumentVersionList | null;
  busy: boolean;
  onRollback: (versionId: string) => void;
}) {
  return (
    <section className="p-3">
      <div className="mb-2 flex items-center gap-2 px-1">
        <HistoryIcon className="size-3.5 text-[#777]" />
        <h3 className="text-xs font-medium">原文件版本</h3>
      </div>
      <div className="space-y-1.5">
        {(versions?.items ?? []).map((version) => (
          <div
            key={version.version_id}
            className="flex items-center gap-3 rounded-lg border border-black/[0.07] bg-white px-3 py-2 dark:border-white/10 dark:bg-black"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-xs">
                <span className="font-mono">V{version.version_number}</span>
                {version.is_active && (
                  <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                    <CheckIcon className="size-3" /> 当前
                  </span>
                )}
              </div>
              <p className="mt-1 truncate text-[10px] text-[#777] dark:text-[#999]">
                {formatDate(version.created_at)} · {formatBytes(version.size_bytes)} ·{" "}
                {version.content_hash.slice(0, 10)}
              </p>
            </div>
            {version.can_rollback && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onRollback(version.version_id)}
                className="h-7 rounded-md border border-black/10 px-2 text-[11px] hover:bg-black/[0.04] disabled:opacity-40 dark:border-white/15 dark:hover:bg-white/10"
              >
                回滚
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function ChunkCard({
  scope,
  documentId,
  chunk,
  onChanged,
  onError,
}: {
  scope: KnowledgeScope;
  documentId: string;
  chunk: KnowledgeChunk;
  onChanged: () => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(chunk.content);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await updateKnowledgeChunk(scope, documentId, chunk.chunk_index, {
        content,
        expected_content_hash: chunk.content_hash,
      });
      setEditing(false);
      await onChanged();
    } catch (caught) {
      onError(caught);
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="rounded-xl border border-black/10 bg-white p-3 dark:border-white/10 dark:bg-black">
      <div className="flex items-center gap-2 text-[11px] text-[#777] dark:text-[#aaa]">
        <span className="font-mono">CHUNK {String(chunk.chunk_index + 1).padStart(3, "0")}</span>
        {chunk.is_manually_edited && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
            已手工编辑
          </span>
        )}
        <span className="ml-auto">{chunk.content.length} 字符</span>
        <button
          type="button"
          onClick={() => {
            setContent(chunk.content);
            setEditing((value) => !value);
          }}
          aria-label={`编辑切片 ${chunk.chunk_index + 1}`}
          className="grid size-7 place-items-center rounded-md hover:bg-black/[0.06] dark:hover:bg-white/10"
        >
          {editing ? <XIcon className="size-3.5" /> : <PencilIcon className="size-3.5" />}
        </button>
      </div>
      {editing ? (
        <div className="mt-3">
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={12}
            aria-label={`切片 ${chunk.chunk_index + 1} 内容`}
            className="w-full resize-y rounded-lg border border-black/15 bg-white p-3 text-xs leading-5 outline-none focus:border-black/40 dark:border-white/20 dark:bg-[#111] dark:focus:border-white/50"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="text-[10px] text-[#777] dark:text-[#999]">
              若切片已被他人修改，保存会被拒绝。
            </span>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving || content.trim().length === 0 || content === chunk.content}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#0d0d0d] px-3 text-xs text-white disabled:opacity-40 dark:bg-white dark:text-black"
            >
              {saving && <LoaderCircleIcon className="size-3.5 animate-spin" />}
              保存并重建向量
            </button>
          </div>
        </div>
      ) : (
        <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words font-sans text-xs leading-5 text-[#333] dark:text-[#d4d4d4]">
          {chunk.content}
        </pre>
      )}
      {!editing && Object.keys(chunk.metadata).length > 0 && (
        <details className="mt-3 border-t border-black/[0.07] pt-2 text-[11px] dark:border-white/10">
          <summary className="cursor-pointer text-[#666] dark:text-[#aaa]">查看元数据</summary>
          <pre className="mt-2 overflow-auto whitespace-pre-wrap font-mono text-[10px]">
            {JSON.stringify(chunk.metadata, null, 2)}
          </pre>
        </details>
      )}
      {!editing && chunk.media.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {chunk.media.map((media) => (
            <Image
              key={media.asset_id}
              src={media.url}
              alt={media.filename}
              width={320}
              height={180}
              unoptimized
              className="max-h-36 w-full rounded-lg border border-black/10 object-contain dark:border-white/10"
            />
          ))}
        </div>
      )}
    </article>
  );
}

function ChunkPagination({
  page,
  onPageChange,
}: {
  page: KnowledgeChunkList;
  onPageChange: (offset: number) => void;
}) {
  return (
    <div className="flex items-center justify-between border-t border-black/10 px-4 py-3 text-xs dark:border-white/10">
      <span className="text-[#777] dark:text-[#aaa]">
        {page.total === 0 ? 0 : page.offset + 1}–{Math.min(page.offset + page.limit, page.total)} /{" "}
        {page.total}
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          onClick={() => onPageChange(Math.max(0, page.offset - page.limit))}
          disabled={page.offset === 0}
          aria-label="上一页切片"
          className="grid size-8 place-items-center rounded-lg border border-black/10 disabled:opacity-30 dark:border-white/15"
        >
          <ChevronLeftIcon className="size-4" />
        </button>
        <button
          type="button"
          onClick={() => onPageChange(page.offset + page.limit)}
          disabled={page.offset + page.limit >= page.total}
          aria-label="下一页切片"
          className="grid size-8 place-items-center rounded-lg border border-black/10 disabled:opacity-30 dark:border-white/15"
        >
          <ChevronRightIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
