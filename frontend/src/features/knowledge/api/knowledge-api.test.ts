import { afterEach, describe, expect, it, vi } from "vitest";

import { createKnowledgeBase, updateKnowledgeChunk } from "@/features/knowledge/api/knowledge-api";

afterEach(() => vi.unstubAllGlobals());

describe("知识库管理 API 客户端", () => {
  it("创建知识库", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        knowledge_base_id: "kb_one",
        name: "产品资料",
        description: "产品文档",
        is_default: false,
        total_documents: 0,
        total_chunks: 0,
        processing_documents: 0,
        failed_documents: 0,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createKnowledgeBase({
      name: "产品资料",
      description: "产品文档",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/knowledge/knowledge-bases",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });

  it("使用 PATCH 和内容哈希更新单个切片", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        chunk_index: 2,
        total_chunks: 3,
        source: "guide.md",
        content: "修订内容",
        content_hash: "b".repeat(64),
        is_manually_edited: true,
        metadata: {},
        media: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateKnowledgeChunk({ knowledgeBaseId: "kb_one" }, "document_one", 2, {
      content: "修订内容",
      expected_content_hash: "a".repeat(64),
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/knowledge/knowledge-bases/kb_one/documents/document_one/chunks/2");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({
      content: "修订内容",
      expected_content_hash: "a".repeat(64),
    });
  });

  it("创建知识库时只发送名称与说明", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        knowledge_base_id: "kb_one",
        name: "产品资料",
        description: "产品文档",
        is_default: false,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createKnowledgeBase({ name: "产品资料", description: "产品文档" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      name: "产品资料",
      description: "产品文档",
    });
  });
});
