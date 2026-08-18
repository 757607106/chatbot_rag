import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SpeechRecognitionRequestError,
  SpeechRecognitionServiceError,
  transcribeSpeech,
} from "@/features/chat/api/asr-client";

afterEach(() => vi.unstubAllGlobals());

describe("语音识别客户端", () => {
  it("上传录音并解析结构化转写", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        Response.json({ text: " 查询本月账单 ", language: "zh", emotion: "neutral" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await transcribeSpeech(new Blob(["audio"], { type: "audio/webm" }));

    expect(result).toEqual({ text: "查询本月账单", language: "zh", emotion: "neutral" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/speech/transcriptions");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("拒绝空录音和非音频内容", async () => {
    await expect(transcribeSpeech(new Blob([], { type: "audio/webm" }))).rejects.toBeInstanceOf(
      SpeechRecognitionRequestError,
    );
    await expect(transcribeSpeech(new Blob(["x"], { type: "text/plain" }))).rejects.toBeInstanceOf(
      SpeechRecognitionRequestError,
    );
  });

  it("映射请求错误与服务错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(Response.json({ detail: "格式错误" }, { status: 415 })),
    );
    await expect(transcribeSpeech(new Blob(["audio"], { type: "audio/webm" }))).rejects.toThrow(
      "格式错误",
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(Response.json({ detail: "上游失败" }, { status: 502 })),
    );
    await expect(
      transcribeSpeech(new Blob(["audio"], { type: "audio/webm" })),
    ).rejects.toBeInstanceOf(SpeechRecognitionServiceError);
  });

  it("拒绝无效的成功响应", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ text: "" })));

    await expect(transcribeSpeech(new Blob(["audio"], { type: "audio/webm" }))).rejects.toThrow(
      "无效的识别结果",
    );
  });
});
