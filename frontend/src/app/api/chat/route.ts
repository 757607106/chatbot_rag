import { NextResponse } from "next/server";

import { getChatUpstreamUrl } from "@/app/api/chatbot-upstream";

export async function POST(request: Request): Promise<Response> {
  const upstreamUrl = getChatUpstreamUrl();

  try {
    const response = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await request.text(),
      cache: "no-store",
      signal: request.signal,
    });

    if (!response.ok) {
      const detail = await readUpstreamError(response);
      return NextResponse.json({ detail }, { status: response.status });
    }

    if (response.body === null) {
      return NextResponse.json({ detail: "聊天服务没有返回可读取的回复流。" }, { status: 502 });
    }

    return new Response(response.body, {
      status: 200,
      headers: {
        "Cache-Control": "no-cache, no-transform",
        "Content-Type": "application/x-ndjson",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    if (request.signal.aborted) {
      return new Response(null, { status: 499 });
    }
    console.error("聊天 BFF 连接 Python 服务失败", error);
    return NextResponse.json(
      { detail: "无法连接聊天服务，请确认 Python API 已启动。" },
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
  return "聊天服务拒绝了本次请求。";
}
