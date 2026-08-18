export type RealtimeVoiceServerEvent =
  | { type: "session.ready" }
  | { type: "input.speech_started" }
  | { type: "input.speech_stopped" }
  | { type: "transcript.user.delta"; text: string; stash: string }
  | { type: "transcript.user.done"; transcript: string }
  | { type: "transcript.assistant.delta"; delta: string }
  | { type: "transcript.assistant.done"; transcript: string }
  | { type: "audio.delta"; audio: string }
  | { type: "tool.started" }
  | { type: "tool.completed" }
  | { type: "response.done" }
  | { type: "error"; code: string; message: string };

export function parseRealtimeVoiceServerEvent(value: string): RealtimeVoiceServerEvent {
  let payload: unknown;
  try {
    payload = JSON.parse(value);
  } catch {
    throw new Error("实时语音服务返回了无效事件。");
  }
  if (!isRecord(payload) || typeof payload.type !== "string") {
    throw new Error("实时语音服务返回了无效事件。");
  }
  switch (payload.type) {
    case "session.ready":
    case "input.speech_started":
    case "input.speech_stopped":
    case "tool.started":
    case "tool.completed":
    case "response.done":
      return { type: payload.type };
    case "transcript.user.delta":
      return {
        type: payload.type,
        text: requireString(payload, "text"),
        stash: requireString(payload, "stash"),
      };
    case "transcript.user.done":
    case "transcript.assistant.done":
      return {
        type: payload.type,
        transcript: requireString(payload, "transcript"),
      };
    case "transcript.assistant.delta":
      return { type: payload.type, delta: requireString(payload, "delta") };
    case "audio.delta":
      return { type: payload.type, audio: requireString(payload, "audio") };
    case "error":
      return {
        type: payload.type,
        code: requireString(payload, "code"),
        message: requireString(payload, "message"),
      };
    default:
      throw new Error("实时语音服务返回了未知事件。");
  }
}

export function getRealtimeVoiceUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_CHATBOT_VOICE_WS_URL?.trim();
  if (!configuredUrl) {
    throw new Error("未配置 NEXT_PUBLIC_CHATBOT_VOICE_WS_URL。");
  }
  let url: URL;
  try {
    url = new URL(configuredUrl);
  } catch {
    throw new Error("NEXT_PUBLIC_CHATBOT_VOICE_WS_URL 不是有效地址。");
  }
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new Error("实时语音地址必须使用 ws 或 wss 协议。");
  }
  return url.toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requireString(value: Record<string, unknown>, field: string): string {
  const result = value[field];
  if (typeof result !== "string") {
    throw new Error(`实时语音事件字段 ${field} 无效。`);
  }
  return result;
}
