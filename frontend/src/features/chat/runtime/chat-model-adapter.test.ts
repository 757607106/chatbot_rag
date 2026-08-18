import { afterEach, describe, expect, it, vi } from "vitest";
import type { ThreadMessage } from "@assistant-ui/react";

import {
  buildConversation,
  ChatRequestError,
  streamAssistantReply,
} from "@/features/chat/runtime/chat-model-adapter";

const encoder = new TextEncoder();

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildConversation", () => {
  it("按 LocalRuntime 当前分支构造完整可见文本历史", () => {
    const messages: ThreadMessage[] = [
      {
        id: "user-1",
        createdAt: new Date("2026-01-01T00:00:00Z"),
        role: "user",
        content: [{ type: "text", text: "上一问" }],
        attachments: [],
        metadata: { custom: {} },
      },
      {
        id: "assistant-1",
        createdAt: new Date("2026-01-01T00:00:01Z"),
        role: "assistant",
        content: [
          { type: "text", text: "上一答" },
          { type: "image", image: "/api/media/example", filename: "示意图.png" },
        ],
        status: { type: "complete", reason: "stop" },
        metadata: {
          unstable_state: null,
          unstable_annotations: [],
          unstable_data: [],
          steps: [],
          custom: {},
        },
      },
      {
        id: "user-2",
        createdAt: new Date("2026-01-01T00:00:02Z"),
        role: "user",
        content: [{ type: "text", text: "继续说明" }],
        attachments: [],
        metadata: { custom: {} },
      },
    ];

    expect(buildConversation(messages)).toEqual([
      { role: "user", content: "上一问" },
      { role: "assistant", content: "上一答" },
      { role: "user", content: "继续说明" },
    ]);
  });
});

describe("streamAssistantReply", () => {
  it("将文本增量累积为 LocalRuntime 需要的完整内容", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              '{"version":3,"type":"message_start","message_id":"reply"}',
              '{"version":3,"type":"text_delta","message_id":"reply","text":"你"}',
              '{"version":3,"type":"text_delta","message_id":"reply","text":"好"}',
              '{"version":3,"type":"message_end","message_id":"reply","finish_reason":"completed"}',
              "",
            ].join("\n"),
          ),
        );
        controller.close();
      },
    });
    let requestBody: BodyInit | null | undefined;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      requestBody = init?.body;
      return new Response(responseBody, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const updates = [];
    const conversation = [
      { role: "user" as const, content: "上一问" },
      { role: "assistant" as const, content: "上一答" },
      { role: "user" as const, content: "测试问题" },
    ];
    for await (const update of streamAssistantReply(conversation, new AbortController().signal)) {
      updates.push(update);
    }

    expect(updates).toEqual([
      { content: [{ type: "text", text: "你" }] },
      { content: [{ type: "text", text: "你好" }] },
    ]);
    expect(JSON.parse(String(requestBody))).toEqual({
      messages: conversation,
    });
  });

  it("将服务端流内错误交给 assistant-ui 错误状态", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":3,"type":"error","code":"agent_error","message":"生成失败"}\n',
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(responseBody, { status: 200 })),
    );

    const consume = async () => {
      for await (const _update of streamAssistantReply(
        [{ role: "user", content: "测试问题" }],
        new AbortController().signal,
      )) {
        // 测试只需驱动适配器消费整条流。
      }
    };

    await expect(consume()).rejects.toEqual(new ChatRequestError("生成失败"));
  });

  it("按文本与图片事件顺序累积 assistant-ui 原生 parts", async () => {
    const assetId = "a".repeat(64);
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              '{"version":3,"type":"message_start","message_id":"reply"}',
              '{"version":3,"type":"text_delta","message_id":"reply","text":"第一步：打开设置。"}',
              `{"version":3,"type":"image_part","message_id":"reply","url":"/api/media/${assetId}","filename":"操作步骤.png"}`,
              '{"version":3,"type":"text_delta","message_id":"reply","text":"第二步：保存。"}',
              '{"version":3,"type":"message_end","message_id":"reply","finish_reason":"completed"}',
              "",
            ].join("\n"),
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(responseBody, { status: 200 })),
    );

    const updates = [];
    for await (const update of streamAssistantReply(
      [{ role: "user", content: "怎么操作？" }],
      new AbortController().signal,
    )) {
      updates.push(update);
    }

    expect(updates.at(-1)).toEqual({
      content: [
        { type: "text", text: "第一步：打开设置。" },
        {
          type: "image",
          image: `/api/media/${assetId}`,
          filename: "操作步骤.png",
        },
        { type: "text", text: "第二步：保存。" },
      ],
    });
  });

  it("把 MCP 状态累计为不包含参数和结果的 tool-call part", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              '{"version":3,"type":"message_start","message_id":"reply"}',
              '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"mcp-1","operation":"list_sales_orders","status":"running"}',
              '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"mcp-1","operation":"list_sales_orders","status":"completed"}',
              '{"version":3,"type":"text_delta","message_id":"reply","text":"查询完成。"}',
              '{"version":3,"type":"message_end","message_id":"reply","finish_reason":"completed"}',
              "",
            ].join("\n"),
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(responseBody, { status: 200 })),
    );

    const updates = [];
    for await (const update of streamAssistantReply(
      [{ role: "user", content: "查询最近销售单" }],
      new AbortController().signal,
    )) {
      updates.push(update);
    }

    expect(updates[0]).toEqual({
      content: [
        {
          type: "tool-call",
          toolCallId: "mcp-1",
          toolName: "list_sales_orders",
          args: {},
          argsText: "",
        },
      ],
    });
    expect(updates.at(-1)).toEqual({
      content: [
        {
          type: "tool-call",
          toolCallId: "mcp-1",
          toolName: "list_sales_orders",
          args: {},
          argsText: "",
          result: { status: "completed" },
        },
        { type: "text", text: "查询完成。" },
      ],
    });
  });

  it("把 MCP 失败状态映射为不公开异常详情的错误 part", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              '{"version":3,"type":"message_start","message_id":"reply"}',
              '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"mcp-1","operation":"external_business","status":"running"}',
              '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"mcp-1","operation":"external_business","status":"failed"}',
              '{"version":3,"type":"text_delta","message_id":"reply","text":"暂时无法查询。"}',
              '{"version":3,"type":"message_end","message_id":"reply","finish_reason":"completed"}',
              "",
            ].join("\n"),
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(responseBody, { status: 200 })),
    );

    const updates = [];
    for await (const update of streamAssistantReply(
      [{ role: "user", content: "查询业务数据" }],
      new AbortController().signal,
    )) {
      updates.push(update);
    }

    expect(updates.at(-1)?.content?.[0]).toEqual({
      type: "tool-call",
      toolCallId: "mcp-1",
      toolName: "external_business",
      args: {},
      argsText: "",
      result: { status: "failed" },
      isError: true,
    });
  });
});
