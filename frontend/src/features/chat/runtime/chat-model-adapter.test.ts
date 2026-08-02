import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatRequestError, streamAssistantReply } from "@/features/chat/runtime/chat-model-adapter";

const encoder = new TextEncoder();

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamAssistantReply", () => {
  it("将文本增量累积为 LocalRuntime 需要的完整内容", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            [
              '{"version":1,"type":"message_start","message_id":"reply"}',
              '{"version":1,"type":"text_delta","message_id":"reply","text":"你"}',
              '{"version":1,"type":"text_delta","message_id":"reply","text":"好"}',
              '{"version":1,"type":"message_end","message_id":"reply","finish_reason":"completed"}',
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
    for await (const update of streamAssistantReply("测试问题", new AbortController().signal)) {
      updates.push(update);
    }

    expect(updates).toEqual([
      { content: [{ type: "text", text: "你" }] },
      { content: [{ type: "text", text: "你好" }] },
    ]);
  });

  it("将服务端流内错误交给 assistant-ui 错误状态", async () => {
    const responseBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":1,"type":"error","code":"agent_error","message":"生成失败"}\n',
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
      for await (const _update of streamAssistantReply("测试问题", new AbortController().signal)) {
        // 测试只需驱动适配器消费整条流。
      }
    };

    await expect(consume()).rejects.toEqual(new ChatRequestError("生成失败"));
  });
});
