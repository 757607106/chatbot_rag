import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/speech/tts/route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.CHATBOT_API_URL;
});

describe("语音合成 BFF", () => {
  it("把文本转发到 Python 语音接口并流式返回 WAV", async () => {
    process.env.CHATBOT_API_URL = "https://backend.example/api/v1/chat/stream";
    const fetchMock = vi.fn(
      async () =>
        new Response(new Uint8Array([0x52, 0x49, 0x46, 0x46]), {
          status: 200,
          headers: { "Content-Type": "audio/wav" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://frontend.test/api/speech/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "朗读这段回复" }),
      }),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.example/api/v1/speech/tts",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "朗读这段回复" }),
        cache: "no-store",
      }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("audio/wav");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([0x52, 0x49, 0x46, 0x46]),
    );
  });

  it("保留上游错误状态和对外文案", async () => {
    process.env.CHATBOT_API_URL = "https://backend.example/api/v1/chat/stream";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "语音合成服务不可用。" }, { status: 503 })),
    );

    const response = await POST(
      new Request("http://frontend.test/api/speech/tts", {
        method: "POST",
        body: JSON.stringify({ text: "你好" }),
      }),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: "语音合成服务不可用。",
    });
  });
});
