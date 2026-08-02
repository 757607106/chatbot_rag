import { describe, expect, it } from "vitest";

import { ChatStreamProtocolError, readChatStream } from "@/features/chat/api/read-chat-stream";

const encoder = new TextEncoder();

describe("readChatStream", () => {
  it("可以跨网络分块重建 NDJSON 事件", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            '{"version":1,"type":"message_start","message_id":"reply"}\n' +
              '{"version":1,"type":"text_delta","message_id":"reply","te',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'xt":"你好"}\n{"version":1,"type":"message_end","message_id":"reply","finish_reason":"completed"}\n',
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
          encoder.encode('{"version":2,"type":"message_start","message_id":"reply"}\n'),
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
});
