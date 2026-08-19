import { NextResponse } from "next/server";

import { getKnowledgeUpstreamUrl } from "@/app/api/chatbot-upstream";

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: RouteContext): Promise<Response> {
  return proxyKnowledgeRequest(request, context);
}

export async function POST(request: Request, context: RouteContext): Promise<Response> {
  return proxyKnowledgeRequest(request, context);
}

export async function DELETE(request: Request, context: RouteContext): Promise<Response> {
  return proxyKnowledgeRequest(request, context);
}

export async function PATCH(request: Request, context: RouteContext): Promise<Response> {
  return proxyKnowledgeRequest(request, context);
}

async function proxyKnowledgeRequest(request: Request, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  if (path.length === 0 || path.some((segment) => !/^[a-zA-Z0-9._-]+$/.test(segment))) {
    return NextResponse.json({ detail: "知识库请求路径无效。" }, { status: 400 });
  }

  const upstreamUrl = new URL(getKnowledgeUpstreamUrl(path.map(encodeURIComponent).join("/")));
  upstreamUrl.search = new URL(request.url).search;
  const contentType = request.headers.get("content-type");
  const headers = new Headers({ Accept: "application/json" });
  if (contentType !== null) headers.set("Content-Type", contentType);
  // 管理密钥仅存在于 Next.js 服务端环境，浏览器不持有任何凭据。
  const managementApiKey = process.env.CHATBOT_MANAGEMENT_API_KEY?.trim();
  if (managementApiKey) headers.set("X-Api-Key", managementApiKey);

  try {
    const response = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": response.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    console.error("知识库 BFF 连接 Python 服务失败", error);
    return NextResponse.json(
      { detail: "无法连接知识库服务，请确认 Python API 已启动。" },
      { status: 502 },
    );
  }
}
