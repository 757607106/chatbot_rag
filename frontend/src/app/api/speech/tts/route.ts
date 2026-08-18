import { NextResponse } from "next/server";

import { getSpeechUpstreamUrl } from "@/app/api/chatbot-upstream";

export async function POST(request: Request): Promise<Response> {
  const upstreamUrl = getSpeechUpstreamUrl("tts");

  try {
    const response = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "audio/wav",
      },
      body: await request.text(),
      cache: "no-store",
      signal: request.signal,
    });

    if (!response.ok) {
      const detail = await readUpstreamError(response);
      return NextResponse.json({ detail }, { status: response.status });
    }

    if (response.body === null) {
      return NextResponse.json({ detail: "语音服务没有返回可播放的音频。" }, { status: 502 });
    }

    return new Response(response.body, {
      status: 200,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "audio/wav",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    console.error("语音 BFF 连接 Python 服务失败", error);
    return NextResponse.json(
      { detail: "无法连接语音服务，请确认 Python API 已启动。" },
      { status: 502 },
    );
  }
}

async function readUpstreamError(response: Response): Promise<string> {
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
    // 非 JSON 错误响应转换为统一对外文案。
  }
  return "语音服务拒绝了本次请求。";
}
