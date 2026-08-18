import { describe, expect, it } from "vitest";

import { ChatStreamProtocolError, readChatStream } from "@/features/chat/api/read-chat-stream";

const encoder = new TextEncoder();

describe("readChatStream", () => {
  it("可以跨网络分块重建 NDJSON 事件", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":3,"type":"message_start","message_id":"reply"}\n' +
              '{"version":3,"type":"text_delta","message_id":"reply","te',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'xt":"你好"}\n{"version":3,"type":"message_end","message_id":"reply","finish_reason":"completed"}\n',
          ),
        );
        controller.close();
      },
    });

    const events = [];
    for await (const event of readChatStream(body)) events.push(event);

    expect(events.map((event) => event.type)).toEqual([
      "message_start",
      "text_delta",
      "message_end",
    ]);
    expect(events[1]).toMatchObject({ text: "你好" });
  });

  it("拒绝未知协议版本", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode('{"version":99,"type":"message_start","message_id":"reply"}\n'),
        );
        controller.close();
      },
    });

    const consume = async () => {
      for await (const _event of readChatStream(body)) {
        // 测试只需驱动解析器消费整条流。
      }
    };

    await expect(consume()).rejects.toBeInstanceOf(ChatStreamProtocolError);
  });

  it("只接受受控的 MCP 工具状态", async () => {
    const validBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"mcp-1","operation":"list_sales_orders","status":"running"}\n',
          ),
        );
        controller.close();
      },
    });
    const validEvents = [];
    for await (const event of readChatStream(validBody)) validEvents.push(event);
    expect(validEvents[0]).toMatchObject({
      type: "tool_status",
      operation: "list_sales_orders",
      status: "running",
    });

    const unsafeBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":3,"type":"tool_status","message_id":"reply","tool_call_id":"internal-id","operation":"mcp__server__listSalesOrders","status":"running"}\n',
          ),
        );
        controller.close();
      },
    });
    const consumeUnsafe = async () => {
      for await (const _event of readChatStream(unsafeBody)) {
        // 测试只需驱动解析器执行边界校验。
      }
    };
    await expect(consumeUnsafe()).rejects.toBeInstanceOf(ChatStreamProtocolError);
  });

  it("只接受同源媒体 BFF 图片地址", async () => {
    const validId = "b".repeat(64);
    const validBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `{"version":3,"type":"image_part","message_id":"reply","url":"/api/media/${validId}","filename":"步骤.png"}\n`,
          ),
        );
        controller.close();
      },
    });
    const validEvents = [];
    for await (const event of readChatStream(validBody)) validEvents.push(event);
    expect(validEvents[0]).toMatchObject({ type: "image_part", filename: "步骤.png" });

    const unsafeBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":3,"type":"image_part","message_id":"reply","url":"https://evil.example/image.png","filename":"图片.png"}\n',
          ),
        );
        controller.close();
      },
    });
    const consumeUnsafe = async () => {
      for await (const _event of readChatStream(unsafeBody)) {
        // 测试只需驱动解析器执行边界校验。
      }
    };
    await expect(consumeUnsafe()).rejects.toBeInstanceOf(ChatStreamProtocolError);
  });
});
