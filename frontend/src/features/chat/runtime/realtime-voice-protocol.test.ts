import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getRealtimeVoiceUrl,
  parseRealtimeVoiceServerEvent,
} from "@/features/chat/runtime/realtime-voice-protocol";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("parseRealtimeVoiceServerEvent", () => {
  it("只接受前后端约定的受控事件", () => {
    expect(
      parseRealtimeVoiceServerEvent(
        JSON.stringify({
          type: "transcript.user.delta",
          text: "稳定文本",
          stash: "临时文本",
        }),
      ),
    ).toEqual({
      type: "transcript.user.delta",
      text: "稳定文本",
      stash: "临时文本",
    });
  });

  it("拒绝未知供应商事件和缺失字段", () => {
    expect(() =>
      parseRealtimeVoiceServerEvent(JSON.stringify({ type: "session.created" })),
    ).toThrow("未知事件");
    expect(() =>
      parseRealtimeVoiceServerEvent(JSON.stringify({ type: "audio.delta", audio: 123 })),
    ).toThrow("audio");
  });
});

describe("getRealtimeVoiceUrl", () => {
  it("只允许显式配置的 WebSocket 地址", () => {
    vi.stubEnv("NEXT_PUBLIC_CHATBOT_VOICE_WS_URL", "wss://chat.example.com/api/v1/voice/realtime");

    expect(getRealtimeVoiceUrl()).toBe("wss://chat.example.com/api/v1/voice/realtime");
  });

  it("拒绝 HTTP 地址", () => {
    vi.stubEnv(
      "NEXT_PUBLIC_CHATBOT_VOICE_WS_URL",
      "https://chat.example.com/api/v1/voice/realtime",
    );

    expect(() => getRealtimeVoiceUrl()).toThrow("ws 或 wss");
  });
});
