import type {
  ChatModelAdapter,
  ChatModelRunResult,
  ThreadAssistantMessagePart,
  ThreadMessage,
} from "@assistant-ui/react";

import { readChatStream } from "@/features/chat/api/read-chat-stream";

export class ChatRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatRequestError";
  }
}

export const chatModelAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const message = findLatestUserText(messages);
    yield* streamAssistantReply(message, abortSignal);
  },
};

export async function* streamAssistantReply(
  message: string,
  abortSignal: AbortSignal,
): AsyncGenerator<ChatModelRunResult, void> {
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      cache: "no-store",
      signal: abortSignal,
    });

    if (!response.ok) {
      throw new ChatRequestError(await readHttpError(response));
    }

    let messageId: string | null = null;
    const content: ThreadAssistantMessagePart[] = [];
    let textPartIndex: number | null = null;
    let completed = false;

    for await (const event of readChatStream(response.body)) {
      if (event.type === "message_start") {
        if (messageId !== null) {
          throw new ChatRequestError("服务器返回了重复的消息开始事件。");
        }
        messageId = event.message_id;
        continue;
      }

      if (event.type === "error") {
        throw new ChatRequestError(event.message);
      }

      if (messageId === null || event.message_id !== messageId) {
        throw new ChatRequestError("回复流中的消息标识不一致。");
      }

      if (event.type === "text_delta") {
        if (!event.text) continue;
        if (textPartIndex === null) {
          textPartIndex = content.length;
          content.push({ type: "text", text: event.text });
        } else {
          const current = content[textPartIndex];
          if (current?.type !== "text") {
            throw new ChatRequestError("回复流中的文本状态无效。");
          }
          content[textPartIndex] = {
            type: "text",
            text: current.text + event.text,
          };
        }
        yield {
          content: [...content],
        };
        continue;
      }

      if (event.type === "image_part") {
        content.push({
          type: "image",
          image: event.url,
          filename: event.filename,
        });
        textPartIndex = null;
        yield { content: [...content] };
        continue;
      }

      if (event.type === "message_end") {
        completed = true;
      }
    }

    if (!completed) {
      throw new ChatRequestError("回复流未正常完成，请重试。");
    }
    if (content.length === 0) {
      throw new ChatRequestError("助手未返回可显示的内容。");
    }
  } catch (error) {
    if (abortSignal.aborted) return;
    throw error;
  }
}

function findLatestUserText(messages: readonly ThreadMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role !== "user") continue;

    const text = message.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n")
      .trim();
    if (text) return text;
  }

  throw new ChatRequestError("请先输入需要查询的问题。");
}

async function readHttpError(response: Response): Promise<string> {
  try {
    const value: unknown = await response.json();
    if (
      typeof value === "object" &&
      value !== null &&
      "detail" in value &&
      typeof value.detail === "string"
    ) {
      return value.detail;
    }
  } catch {
    // 非 JSON 错误响应使用统一公开文案。
  }
  return "聊天服务暂时不可用，请稍后重试。";
}
