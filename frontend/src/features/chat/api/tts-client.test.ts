import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SpeechSynthesisRequestError,
  SpeechSynthesisServiceError,
  synthesizeSpeech,
} from "@/features/chat/api/tts-client";

afterEach(() => vi.unstubAllGlobals());

function wavResponse(): Response {
  return new Response(new Uint8Array([0x52, 0x49, 0x46, 0x46]).buffer, {
    status: 200,
    headers: { "Content-Type": "audio/wav" },
  });
}

describe("语音合成客户端", () => {
  it("发送文本并返回音频字节", async () => {
    const fetchMock = vi.fn().mockResolvedValue(wavResponse());
    vi.stubGlobal("fetch", fetchMock);

    const audio = await synthesizeSpeech("朗读这段回复");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/speech/tts");
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    expect(JSON.parse(String(init.body))).toEqual({ text: "朗读这段回复" });
    expect(audio.byteLength).toBe(4);
  });

  it("透传终止信号", async () => {
    const abortController = new AbortController();
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      expect(init.signal).toBe(abortController.signal);
      return Promise.resolve(wavResponse());
    });
    vi.stubGlobal("fetch", fetchMock);

    await synthesizeSpeech("你好", abortController.signal);
  });

  it("把 422 映射为请求错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "无效" }, { status: 422 })),
    );

    await expect(synthesizeSpeech("x".repeat(20_001))).rejects.toBeInstanceOf(
      SpeechSynthesisRequestError,
    );
  });

  it.each([502, 503])("把 %s 映射为服务错误", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "失败" }, { status })),
    );

    await expect(synthesizeSpeech("你好")).rejects.toBeInstanceOf(SpeechSynthesisServiceError);
  });

  it("拒绝非音频内容类型", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ok: true }, { status: 200 })));

    await expect(synthesizeSpeech("你好")).rejects.toThrow("无法播放的内容");
  });

  it("网络异常映射为服务错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(synthesizeSpeech("你好")).rejects.toBeInstanceOf(SpeechSynthesisServiceError);
  });
});
