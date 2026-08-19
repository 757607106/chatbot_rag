"use client";

import {
  AlertCircleIcon,
  DatabaseIcon,
  LoaderCircleIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  KnowledgeApiError,
  listKnowledgeBases,
  listKnowledgeDocuments,
  uploadKnowledgeDocument,
} from "@/features/knowledge/api/knowledge-api";
import { KnowledgeDocumentsPanel } from "@/features/knowledge/components/knowledge-documents-panel";
import { KnowledgeRetrievalPanel } from "@/features/knowledge/components/knowledge-retrieval-panel";
import type {
  KnowledgeBaseSummary,
  KnowledgeDocumentList,
  KnowledgeScope,
} from "@/features/knowledge/schemas/knowledge";
import { cn } from "@/lib/utils";

type WorkspaceTab = "documents" | "retrieval";

export function KnowledgeWorkspace() {
  const [initializing, setInitializing] = useState(true);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<KnowledgeDocumentList | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("documents");
  const [showCreatePanel, setShowCreatePanel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scope = useMemo<KnowledgeScope | null>(
    () => (selectedKnowledgeBaseId === null ? null : { knowledgeBaseId: selectedKnowledgeBaseId }),
    [selectedKnowledgeBaseId],
  );
  const handleApiError = useCallback((caught: unknown) => {
    setError(caught instanceof Error ? caught.message : "知识库操作失败。");
  }, []);

  const loadDocuments = useCallback(
    async (targetScope: KnowledgeScope, showLoading = false) => {
      if (showLoading) setLoading(true);
      try {
        const nextSnapshot = await listKnowledgeDocuments(targetScope);
        setSnapshot(nextSnapshot);
        setKnowledgeBases((current) =>
          current.map((item) =>
            item.knowledge_base_id === nextSnapshot.knowledge_base_id
              ? {
                  ...item,
                  total_documents: nextSnapshot.total_documents,
                  total_chunks: nextSnapshot.total_chunks,
                  processing_documents: nextSnapshot.processing_documents,
                  failed_documents: nextSnapshot.failed_documents,
                }
              : item,
          ),
        );
        setError(null);
      } catch (caught) {
        handleApiError(caught);
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [handleApiError],
  );

  const initializeWorkspace = useCallback(
    async (preferredKnowledgeBaseId?: string) => {
      setLoading(true);
      setSnapshot(null);
      try {
        const response = await listKnowledgeBases();
        setKnowledgeBases(response.items);
        const selected =
          response.items.find((item) => item.knowledge_base_id === preferredKnowledgeBaseId) ??
          response.items.find((item) => item.is_default) ??
          response.items[0] ??
          null;
        setSelectedKnowledgeBaseId(selected?.knowledge_base_id ?? null);
        if (selected !== null) {
          await loadDocuments({ knowledgeBaseId: selected.knowledge_base_id });
        }
      } catch (caught) {
        handleApiError(caught);
      } finally {
        setLoading(false);
      }
    },
    [handleApiError, loadDocuments],
  );

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      await initializeWorkspace();
      if (active) setInitializing(false);
    });
    return () => {
      active = false;
    };
  }, [initializeWorkspace]);

  const hasProcessingDocuments =
    snapshot?.processing_documents !== undefined && snapshot.processing_documents > 0;
  useEffect(() => {
    if (!hasProcessingDocuments || scope === null) return;
    const timer = window.setInterval(() => void loadDocuments(scope), 2_000);
    return () => window.clearInterval(timer);
  }, [hasProcessingDocuments, loadDocuments, scope]);

  const selectKnowledgeBase = async (knowledgeBaseId: string) => {
    setSelectedKnowledgeBaseId(knowledgeBaseId);
    setSnapshot(null);
    setSearch("");
    setTab("documents");
    await loadDocuments({ knowledgeBaseId }, true);
  };

  const handleDeleteKnowledgeBase = async (knowledgeBaseId: string) => {
    const target = knowledgeBases.find((item) => item.knowledge_base_id === knowledgeBaseId);
    if (
      target === undefined ||
      !window.confirm(
        `确定删除知识库“${target.name}”吗？仅允许删除已清空文档的非默认知识库，删除后会同时移除其文档目录与向量集合。`,
      )
    ) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await deleteKnowledgeBase(knowledgeBaseId);
      await initializeWorkspace();
    } catch (caught) {
      handleApiError(caught);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (file: File) => {
    if (scope === null) return;
    setLoading(true);
    setError(null);
    try {
      await uploadKnowledgeDocument(scope, file, false);
      await loadDocuments(scope);
    } catch (caught) {
      if (
        caught instanceof KnowledgeApiError &&
        caught.status === 409 &&
        window.confirm(`“${file.name}”已经存在。是否明确替换当前知识库中的该文档？`)
      ) {
        try {
          await uploadKnowledgeDocument(scope, file, true);
          await loadDocuments(scope);
        } catch (replaceError) {
          handleApiError(replaceError);
        }
      } else {
        handleApiError(caught);
      }
    } finally {
      setLoading(false);
      if (fileInputRef.current !== null) fileInputRef.current.value = "";
    }
  };

  if (initializing) return <WorkspaceLoading />;

  return (
    <div className="h-full overflow-y-auto bg-white text-[#0d0d0d] dark:bg-black dark:text-[#ececec]">
      <div className="mx-auto flex min-h-full w-full max-w-[1520px] flex-col px-5 pt-14 pb-7 sm:py-7 md:px-8 lg:px-10">
        <header className="flex flex-col gap-5 border-b border-black/10 pb-5 dark:border-white/10 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-lg font-medium tracking-[-0.025em]">知识库控制面</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => scope !== null && void loadDocuments(scope, true)}
              disabled={loading || scope === null}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-black/10 px-3 text-sm hover:bg-black/[0.04] disabled:opacity-50 dark:border-white/15 dark:hover:bg-white/10"
            >
              <RefreshCwIcon className={cn("size-4", loading && "animate-spin")} />
              刷新
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading || scope === null}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#0d0d0d] px-3 text-sm text-white hover:bg-[#2b2b2b] disabled:opacity-50 dark:bg-white dark:text-black dark:hover:bg-[#e5e5e5]"
            >
              <UploadIcon className="size-4" />
              上传文档
            </button>
            <input
              ref={fileInputRef}
              type="file"
              className="sr-only"
              accept=".docx,.md,.markdown,.pdf,.pptx,.txt,.xls,.xlsx"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file !== undefined) void handleUpload(file);
              }}
            />
          </div>
        </header>

        <KnowledgeBaseSelector
          knowledgeBases={knowledgeBases}
          selectedKnowledgeBaseId={selectedKnowledgeBaseId}
          onKnowledgeBaseChange={(knowledgeBaseId) => void selectKnowledgeBase(knowledgeBaseId)}
          onCreateKnowledgeBase={() => setShowCreatePanel((value) => !value)}
          onDeleteKnowledgeBase={(knowledgeBaseId) =>
            void handleDeleteKnowledgeBase(knowledgeBaseId)
          }
        />

        {showCreatePanel && (
          <CreateKnowledgeBasePanel
            onCancel={() => setShowCreatePanel(false)}
            onSubmit={async (name, description) => {
              try {
                const created = await createKnowledgeBase({ name, description });
                setShowCreatePanel(false);
                await initializeWorkspace(created.knowledge_base_id);
              } catch (caught) {
                handleApiError(caught);
              }
            }}
          />
        )}

        {error !== null && (
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200">
            <AlertCircleIcon className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
            <button
              type="button"
              aria-label="关闭错误提示"
              onClick={() => setError(null)}
              className="ml-auto"
            >
              <XIcon className="size-4" />
            </button>
          </div>
        )}

        {scope === null ? (
          <EmptyKnowledgeBase onCreate={() => setShowCreatePanel(true)} />
        ) : (
          <>
            <nav
              className="mt-5 flex gap-6 border-b border-black/10 dark:border-white/10"
              aria-label="知识库功能"
            >
              <WorkspaceTabButton active={tab === "documents"} onClick={() => setTab("documents")}>
                文档
              </WorkspaceTabButton>
              <WorkspaceTabButton active={tab === "retrieval"} onClick={() => setTab("retrieval")}>
                召回测试
              </WorkspaceTabButton>
            </nav>
            <div className="mt-5">
              {tab === "documents" ? (
                <KnowledgeDocumentsPanel
                  scope={scope}
                  snapshot={snapshot}
                  search={search}
                  onSearchChange={setSearch}
                  onChanged={() => loadDocuments(scope)}
                  onError={handleApiError}
                />
              ) : (
                <KnowledgeRetrievalPanel scope={scope} onError={handleApiError} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function KnowledgeBaseSelector({
  knowledgeBases,
  selectedKnowledgeBaseId,
  onKnowledgeBaseChange,
  onCreateKnowledgeBase,
  onDeleteKnowledgeBase,
}: {
  knowledgeBases: KnowledgeBaseSummary[];
  selectedKnowledgeBaseId: string | null;
  onKnowledgeBaseChange: (knowledgeBaseId: string) => void;
  onCreateKnowledgeBase: () => void;
  onDeleteKnowledgeBase: (knowledgeBaseId: string) => void;
}) {
  return (
    <section className="mt-5 rounded-2xl border border-black/10 bg-[#fafafa] p-3 dark:border-white/10 dark:bg-[#151515]">
      <div className="flex items-center gap-2 text-xs text-[#777] dark:text-[#999]">
        <DatabaseIcon className="size-4" />
        <span>每个知识库拥有独立文档目录与 Qdrant collection</span>
      </div>
      <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
        {knowledgeBases.map((item) => (
          <div key={item.knowledge_base_id} className="flex min-w-52 items-stretch gap-1">
            <button
              type="button"
              onClick={() => onKnowledgeBaseChange(item.knowledge_base_id)}
              className={cn(
                "flex-1 rounded-xl border px-3 py-2.5 text-left transition-colors",
                selectedKnowledgeBaseId === item.knowledge_base_id
                  ? "border-[#0d0d0d] bg-[#0d0d0d] text-white dark:border-white dark:bg-white dark:text-black"
                  : "border-black/10 bg-white hover:border-black/25 dark:border-white/10 dark:bg-black dark:hover:border-white/30",
              )}
            >
              <span className="flex items-center gap-2 text-sm font-medium">
                <DatabaseIcon className="size-3.5" />
                <span className="truncate">{item.name}</span>
              </span>
              <span
                className={cn(
                  "mt-1.5 block text-[10px]",
                  selectedKnowledgeBaseId === item.knowledge_base_id
                    ? "text-white/65 dark:text-black/60"
                    : "text-[#777] dark:text-[#999]",
                )}
              >
                {item.total_documents} 文档 · {item.total_chunks} 切片
              </span>
            </button>
            {!item.is_default && selectedKnowledgeBaseId === item.knowledge_base_id && (
              <button
                type="button"
                aria-label={`删除知识库 ${item.name}`}
                title="删除知识库"
                onClick={() => onDeleteKnowledgeBase(item.knowledge_base_id)}
                className="grid w-9 place-items-center rounded-xl border border-black/10 text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-white/10 dark:text-red-300 dark:hover:border-red-800 dark:hover:bg-red-950/40"
              >
                <Trash2Icon className="size-4" />
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          onClick={onCreateKnowledgeBase}
          className="grid min-w-36 place-items-center rounded-xl border border-dashed border-black/20 px-3 py-2.5 text-xs text-[#666] hover:border-black/40 hover:text-black dark:border-white/20 dark:text-[#aaa] dark:hover:border-white/40 dark:hover:text-white"
        >
          <span className="inline-flex items-center gap-1.5">
            <PlusIcon className="size-3.5" /> 新建知识库
          </span>
        </button>
      </div>
    </section>
  );
}

function CreateKnowledgeBasePanel({
  onCancel,
  onSubmit,
}: {
  onCancel: () => void;
  onSubmit: (name: string, description: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit(name, description);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="mt-3 grid gap-3 rounded-xl border border-black/10 bg-white p-4 shadow-[0_12px_40px_rgba(0,0,0,0.06)] md:grid-cols-[240px_minmax(260px,1fr)_auto] md:items-end dark:border-white/15 dark:bg-[#111] dark:shadow-none"
    >
      <label className="text-xs font-medium">
        知识库名称
        <input
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={80}
          required
          className="mt-2 h-9 w-full rounded-lg border border-black/15 bg-transparent px-3 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
        />
      </label>
      <label className="text-xs font-medium">
        说明
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={500}
          placeholder="说明包含什么资料、何时应检索"
          className="mt-2 h-9 w-full rounded-lg border border-black/15 bg-transparent px-3 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
        />
      </label>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="h-9 rounded-lg border border-black/10 px-3 text-xs dark:border-white/15"
        >
          取消
        </button>
        <button
          type="submit"
          disabled={submitting || name.trim().length === 0}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#0d0d0d] px-3 text-xs text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {submitting && <LoaderCircleIcon className="size-3.5 animate-spin" />}
          创建知识库
        </button>
      </div>
    </form>
  );
}

function EmptyKnowledgeBase({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="mt-8 grid min-h-72 place-items-center rounded-2xl border border-dashed border-black/15 px-6 text-center dark:border-white/20">
      <div>
        <DatabaseIcon className="mx-auto size-8 text-[#999]" />
        <p className="mt-3 text-sm font-medium">还没有知识库</p>
        <p className="mt-1 text-xs text-[#777] dark:text-[#aaa]">创建后即可上传文档并测试召回。</p>
        <button
          type="button"
          onClick={onCreate}
          className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#0d0d0d] px-3 text-xs text-white dark:bg-white dark:text-black"
        >
          <PlusIcon className="size-3.5" /> 创建知识库
        </button>
      </div>
    </div>
  );
}

function WorkspaceLoading() {
  return (
    <div className="grid h-full place-items-center bg-white dark:bg-black">
      <div className="flex items-center gap-3 text-sm text-[#666] dark:text-[#aaa]">
        <LoaderCircleIcon className="size-5 animate-spin" />
        正在连接知识库管理服务…
      </div>
    </div>
  );
}

function WorkspaceTabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "border-b-2 px-0.5 pb-3 text-sm transition-colors",
        active
          ? "border-[#0d0d0d] text-[#0d0d0d] dark:border-white dark:text-white"
          : "border-transparent text-[#777] hover:text-[#0d0d0d] dark:text-[#999] dark:hover:text-white",
      )}
    >
      {children}
    </button>
  );
}
