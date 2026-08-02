import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/media/[asset-id]/route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.CHATBOT_API_URL;
});

describe("media BFF", () => {
  it("通过 Python 媒体接口转发受控图片", async () => {
    const assetId = "c".repeat(64);
    process.env.CHATBOT_API_URL = "https://backend.example/api/v1/chat/stream";
    const fetchMock = vi.fn(
      async () =>
        new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: {
            "Content-Type": "image/png",
            "Content-Disposition": 'inline; filename="step.png"',
          },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request(`http://frontend.test/api/media/${assetId}`), {
      params: Promise.resolve({ "asset-id": assetId }),
    });

    expect(fetchMock).toHaveBeenCalledWith(
      `https://backend.example/api/v1/media/${assetId}`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("拒绝格式无效的图片资产标识", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://frontend.test/api/media/invalid"), {
      params: Promise.resolve({ "asset-id": "invalid" }),
    });

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
