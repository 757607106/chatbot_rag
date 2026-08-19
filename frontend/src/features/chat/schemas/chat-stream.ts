export const CHAT_PROTOCOL_VERSION = 3 as const;

export const MCP_TOOL_OPERATIONS = [
  "list_products",
  "search_products",
  "search_billing_references",
  "preview_sales_order",
  "get_sales_order",
  "list_sales_orders",
  "external_business",
] as const;

export type McpToolOperation = (typeof MCP_TOOL_OPERATIONS)[number];

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

export type ChatImagePartEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "image_part";
  message_id: string;
  url: string;
  filename: string;
};

export type ChatToolStatusEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "tool_status";
  message_id: string;
  tool_call_id: string;
  operation: McpToolOperation;
  status: "running" | "completed" | "failed";
};

export type ChatMessageEndEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "message_end";
  message_id: string;
  finish_reason: "completed";
};

export type ChatErrorCode =
  | "agent_error"
  | "external_tool_error"
  | "incomplete_stream"
  | "protocol_error";

export type ChatErrorEvent = {
  version: typeof CHAT_PROTOCOL_VERSION;
  type: "error";
  code: ChatErrorCode;
  message: string;
};

export type ChatStreamEvent =
  | ChatMessageStartEvent
  | ChatTextDeltaEvent
  | ChatImagePartEvent
  | ChatToolStatusEvent
  | ChatMessageEndEvent
  | ChatErrorEvent;
