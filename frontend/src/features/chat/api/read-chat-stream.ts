import { CHAT_PROTOCOL_VERSION, type ChatStreamEvent } from "@/features/chat/schemas/chat-stream";

const MAX_EVENT_LINE_LENGTH = 128 * 1024;
const MEDIA_URL_PATTERN = /^\/api\/media\/[0-9a-f]{64}$/;

export class ChatStreamProtocolError extends Error {
  constructor(message = "回复流格式无效，请重试。") {
    super(message);
    this.name = "ChatStreamProtocolError";
  }
}

export async function* readChatStream(
  body: ReadableStream<Uint8Array> | null,
): AsyncGenerator<ChatStreamEvent> {
  if (body === null) {
    throw new ChatStreamProtocolError("服务器没有返回可读取的回复流。");
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      if (buffer.length > MAX_EVENT_LINE_LENGTH && !buffer.includes("\n")) {
        throw new ChatStreamProtocolError("回复流中的单个事件过大。");
      }

      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex >= 0) {
        const line = buffer.slice(0, newlineIndex).trim();
        buffer = buffer.slice(newlineIndex + 1);
        if (line) yield parseChatStreamEvent(line);
        newlineIndex = buffer.indexOf("\n");
      }
    }

    buffer += decoder.decode();
    const finalLine = buffer.trim();
    if (finalLine) yield parseChatStreamEvent(finalLine);
  } finally {
    reader.releaseLock();
  }
}

export function parseChatStreamEvent(line: string): ChatStreamEvent {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new ChatStreamProtocolError();
  }

  if (!isRecord(value) || value.version !== CHAT_PROTOCOL_VERSION) {
    throw new ChatStreamProtocolError();
  }

  switch (value.type) {
    case "message_start":
      if (typeof value.message_id === "string") return value as ChatStreamEvent;
      break;
    case "text_delta":
      if (typeof value.message_id === "string" && typeof value.text === "string") {
        return value as ChatStreamEvent;
      }
      break;
    case "image_part":
      if (
        typeof value.message_id === "string" &&
        typeof value.url === "string" &&
        MEDIA_URL_PATTERN.test(value.url) &&
        typeof value.filename === "string" &&
        value.filename.length > 0 &&
        value.filename.length <= 180
      ) {
        return value as ChatStreamEvent;
      }
      break;
    case "message_end":
      if (typeof value.message_id === "string" && value.finish_reason === "completed") {
        return value as ChatStreamEvent;
      }
      break;
    case "error":
      if (typeof value.code === "string" && typeof value.message === "string") {
        return value as ChatStreamEvent;
      }
      break;
  }

  throw new ChatStreamProtocolError();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
