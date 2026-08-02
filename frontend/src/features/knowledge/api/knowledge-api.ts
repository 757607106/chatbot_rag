import type {
  KnowledgeBaseList,
  KnowledgeBaseSummary,
  KnowledgeChunk,
  KnowledgeChunkList,
  KnowledgeDocumentList,
  KnowledgeDocumentVersionList,
  KnowledgeMutation,
  KnowledgeScope,
  RetrievalTestResult,
} from "@/features/knowledge/schemas/knowledge";

export class KnowledgeApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "KnowledgeApiError";
  }
}

export async function listKnowledgeBases(): Promise<KnowledgeBaseList> {
  return requestJson<KnowledgeBaseList>("/api/knowledge/knowledge-bases");
}

export async function createKnowledgeBase(input: {
  name: string;
  description: string;
}): Promise<KnowledgeBaseSummary> {
  return requestJson<KnowledgeBaseSummary>(
    "/api/knowledge/knowledge-bases",
    jsonRequest("POST", input),
  );
}

export async function listKnowledgeDocuments(
  scope: KnowledgeScope,
): Promise<KnowledgeDocumentList> {
  return requestJson<KnowledgeDocumentList>(`${scopePath(scope)}/documents`);
}

export async function uploadKnowledgeDocument(
  scope: KnowledgeScope,
  file: File,
  replace: boolean,
): Promise<KnowledgeMutation> {
  const body = new FormData();
  body.set("file", file);
  return requestJson<KnowledgeMutation>(
    `${scopePath(scope)}/documents?replace=${replace ? "true" : "false"}`,
    { method: "POST", body },
  );
}

export async function reindexKnowledgeDocument(
  scope: KnowledgeScope,
  documentId: string,
): Promise<KnowledgeMutation> {
  return requestJson<KnowledgeMutation>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}/reindex`,
    { method: "POST" },
  );
}

export async function deleteKnowledgeDocument(
  scope: KnowledgeScope,
  documentId: string,
): Promise<KnowledgeMutation> {
  return requestJson<KnowledgeMutation>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE" },
  );
}

export async function listKnowledgeChunks(
  scope: KnowledgeScope,
  documentId: string,
  offset: number,
  limit: number,
): Promise<KnowledgeChunkList> {
  return requestJson<KnowledgeChunkList>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}/chunks?offset=${offset}&limit=${limit}`,
  );
}

export async function updateKnowledgeChunk(
  scope: KnowledgeScope,
  documentId: string,
  chunkIndex: number,
  input: { content: string; expected_content_hash: string },
): Promise<KnowledgeChunk> {
  return requestJson<KnowledgeChunk>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}/chunks/${chunkIndex}`,
    jsonRequest("PATCH", input),
  );
}

export async function listDocumentVersions(
  scope: KnowledgeScope,
  documentId: string,
): Promise<KnowledgeDocumentVersionList> {
  return requestJson<KnowledgeDocumentVersionList>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}/versions`,
  );
}

export async function rollbackDocumentVersion(
  scope: KnowledgeScope,
  documentId: string,
  versionId: string,
): Promise<KnowledgeMutation> {
  return requestJson<KnowledgeMutation>(
    `${scopePath(scope)}/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/rollback`,
    { method: "POST" },
  );
}

export async function runRetrievalTest(
  scope: KnowledgeScope,
  input: {
    query: string;
    top_k: number;
    candidate_top_k: number;
    score_threshold: number | null;
  },
): Promise<RetrievalTestResult> {
  return requestJson<RetrievalTestResult>(
    `${scopePath(scope)}/retrieval-tests`,
    jsonRequest("POST", input),
  );
}

function scopePath(scope: KnowledgeScope): string {
  return `/api/knowledge/knowledge-bases/${encodeURIComponent(scope.knowledgeBaseId)}`;
}

function jsonRequest(method: "POST" | "PATCH", value: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store" });
  await ensureResponse(response);
  return (await response.json()) as T;
}

async function ensureResponse(response: Response): Promise<void> {
  if (response.ok) return;
  let detail = "知识库请求失败。";
  try {
    const value: unknown = await response.json();
    if (
      typeof value === "object" &&
      value !== null &&
      "detail" in value &&
      typeof value.detail === "string"
    ) {
      detail = value.detail;
    }
  } catch {
    // 非 JSON 错误统一使用公开文案。
  }
  throw new KnowledgeApiError(detail, response.status);
}
