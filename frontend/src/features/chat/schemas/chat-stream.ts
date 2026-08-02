export const CHAT_PROTOCOL_VERSION = 1 as const;

export type ChatMessageStartEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "message_start";
  message_id: string;
};

export type ChatTextDeltaEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "text_delta";
  message_id: string;
  text: string;
};

export type ChatMessageEndEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "message_end";
  message_id: string;
  finish_reason: "completed";
};

export type ChatErrorEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "error";
  code: "agent_error" | "incomplete_stream" | "protocol_error";
  message: string;
};

export type ChatStreamEvent =
  | ChatMessageStartEvent
  | ChatTextDeltaEvent
  | ChatMessageEndEvent
  | ChatErrorEvent;
