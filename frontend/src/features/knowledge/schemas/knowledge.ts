export type KnowledgeBaseSummary = {
  knowledge_base_id: string;
  name: string;
  description: string;
  is_default: boolean;
  total_documents: number;
  total_chunks: number;
  processing_documents: number;
  failed_documents: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBaseList = {
  items: KnowledgeBaseSummary[];
};

export type DocumentStatus =
  | "queued"
  | "processing"
  | "ready"
  | "failed"
  | "unsupported"
  | "deleting";

export type KnowledgeJob = {
  job_id: string;
  operation: "index" | "reindex" | "rollback" | "delete";
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocument = {
  document_id: string;
  knowledge_base_id: string;
  source_path: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  status: DocumentStatus;
  chunk_count: number;
  has_active_index: boolean;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  latest_job: KnowledgeJob | null;
};

export type KnowledgeDocumentList = {
  knowledge_base_id: string;
  knowledge_base_name: string;
  total_documents: number;
  total_chunks: number;
  ready_documents: number;
  processing_documents: number;
  failed_documents: number;
  supported_extensions: string[];
  max_upload_bytes: number;
  items: KnowledgeDocument[];
};

export type KnowledgeMutation = {
  document: KnowledgeDocument;
  job: KnowledgeJob;
};

export type KnowledgeChunk = {
  chunk_index: number;
  total_chunks: number;
  source: string;
  content: string;
  content_hash: string;
  is_manually_edited: boolean;
  metadata: Record<string, unknown>;
  media: Array<{ asset_id: string; filename: string; url: string }>;
};

export type KnowledgeChunkList = {
  document_id: string;
  total: number;
  offset: number;
  limit: number;
  items: KnowledgeChunk[];
};

export type KnowledgeDocumentVersion = {
  version_id: string;
  document_id: string;
  version_number: number;
  content_hash: string;
  size_bytes: number;
  status: "queued" | "processing" | "active" | "inactive" | "failed" | "deleted";
  is_active: boolean;
  can_rollback: boolean;
  created_at: string;
};

export type KnowledgeDocumentVersionList = {
  document_id: string;
  items: KnowledgeDocumentVersion[];
};

export type RetrievalCandidate = {
  document_id: string;
  source: string;
  chunk_index: number;
  total_chunks: number;
  content: string;
  metadata: Record<string, unknown>;
  vector_rank: number;
  vector_score: number;
  final_rank: number | null;
  rerank_score: number | null;
};

export type RetrievalTestResult = {
  query: string;
  rerank_status: "succeeded" | "skipped" | "fallback";
  vector_elapsed_ms: number;
  rerank_elapsed_ms: number;
  total_elapsed_ms: number;
  vector_candidates: RetrievalCandidate[];
  final_results: RetrievalCandidate[];
};

export type KnowledgeScope = {
  knowledgeBaseId: string;
};
