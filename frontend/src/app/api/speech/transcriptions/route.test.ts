import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/speech/transcriptions/route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.CHATBOT_API_URL;
});

function uploadRequest(file?: File): Request {
  const body = new FormData();
  if (file) body.append("file", file);
  return new Request("http://frontend.test/api/speech/transcriptions", {
    method: "POST",
    body,
  });
}

describe("语音识别 BFF", () => {
  it("把录音转发到 Python ASR 并返回识别结果", async () => {
    process.env.CHATBOT_API_URL = "https://backend.example/api/v1/chat/stream";
    const fetchMock = vi
      .fn()
      .mockResolvedValue(Response.json({ text: "查询账单", language: "zh", emotion: "neutral" }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      uploadRequest(new File(["audio"], "voice.webm", { type: "audio/webm" })),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.example/api/v1/speech/transcriptions",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      text: "查询账单",
      language: "zh",
      emotion: "neutral",
    });
  });

  it("拒绝缺失、空内容和非音频文件", async () => {
    const missing = await POST(uploadRequest());
    const empty = await POST(uploadRequest(new File([], "empty.webm", { type: "audio/webm" })));
    const unsupported = await POST(
      uploadRequest(new File(["text"], "voice.txt", { type: "text/plain" })),
    );

    expect(missing.status).toBe(422);
    expect(empty.status).toBe(422);
    expect(unsupported.status).toBe(415);
  });

  it("保留上游错误状态和文案", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "语音识别失败" }, { status: 502 })),
    );

    const response = await POST(
      uploadRequest(new File(["audio"], "voice.webm", { type: "audio/webm" })),
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ detail: "语音识别失败" });
  });
});
