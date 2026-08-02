import { getMediaUpstreamUrl } from "@/app/api/chatbot-upstream";

const ASSET_ID_PATTERN = /^[0-9a-f]{64}$/;

type MediaRouteContext = {
  params: Promise<{ "asset-id": string }>;
};

export async function GET(request: Request, context: MediaRouteContext): Promise<Response> {
  const { "asset-id": assetId } = await context.params;
  if (!ASSET_ID_PATTERN.test(assetId)) {
    return new Response(null, { status: 404 });
  }

  try {
    const response = await fetch(getMediaUpstreamUrl(assetId), {
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok || response.body === null) {
      return new Response(null, { status: response.status });
    }

    const headers = new Headers({
      "Cache-Control": response.headers.get("cache-control") ?? "private, max-age=3600",
      "Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
      "X-Content-Type-Options": "nosniff",
    });
    const contentDisposition = response.headers.get("content-disposition");
    if (contentDisposition) headers.set("Content-Disposition", contentDisposition);

    return new Response(response.body, {
      status: 200,
      headers,
    });
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    console.error("图片 BFF 连接 Python 服务失败", error);
    return new Response(null, { status: 502 });
  }
}
