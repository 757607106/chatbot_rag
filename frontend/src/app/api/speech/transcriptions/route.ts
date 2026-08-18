import { NextResponse } from "next/server";

import { getSpeechUpstreamUrl } from "@/app/api/chatbot-upstream";

const MAX_AUDIO_BYTES = 10 * 1024 * 1024;
const SUPPORTED_AUDIO_TYPES = new Set([
  "audio/aac",
  "audio/flac",
  "audio/mp4",
  "audio/mpeg",
  "audio/ogg",
  "audio/opus",
  "audio/wav",
  "audio/webm",
  "audio/x-m4a",
]);

export async function POST(request: Request): Promise<Response> {
  let file: File;
  try {
    const formData = await request.formData();
    const value = formData.get("file");
    if (!(value instanceof File)) {
      return NextResponse.json({ detail: "请提供录音文件。" }, { status: 422 });
    }
    file = value;
  } catch {
    return NextResponse.json({ detail: "录音上传格式无效。" }, { status: 400 });
  }

  const mediaType = file.type.split(";", 1)[0]?.toLowerCase() ?? "";
  if (!SUPPORTED_AUDIO_TYPES.has(mediaType)) {
    return NextResponse.json({ detail: "不支持该录音格式。" }, { status: 415 });
  }
  if (file.size === 0) {
    return NextResponse.json({ detail: "录音内容为空。" }, { status: 422 });
  }
  if (file.size > MAX_AUDIO_BYTES) {
    return NextResponse.json({ detail: "录音文件不能超过 10MB。" }, { status: 413 });
  }

  const upstreamBody = new FormData();
  upstreamBody.append("file", file, normalizeFilename(file.name, mediaType));

  try {
    const response = await fetch(getSpeechUpstreamUrl("transcriptions"), {
      method: "POST",
      body: upstreamBody,
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok) {
      return NextResponse.json(
        { detail: await readUpstreamError(response) },
        { status: response.status },
      );
    }

    const payload: unknown = await response.json();
    if (!isTranscriptionResponse(payload)) {
      return NextResponse.json({ detail: "语音服务返回了无效结果。" }, { status: 502 });
    }
    return NextResponse.json(payload, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    console.error("语音识别 BFF 连接 Python 服务失败", error);
    return NextResponse.json(
      { detail: "无法连接语音识别服务，请确认 Python API 已启动。" },
      { status: 502 },
    );
  }
}

function normalizeFilename(filename: string, mediaType: string): string {
  const safeName = filename.trim().replaceAll(/[^a-zA-Z0-9._-]/g, "_");
  if (safeName) return safeName.slice(0, 120);
  const extension = mediaType === "audio/mp4" ? "m4a" : mediaType.split("/")[1] || "webm";
  return `dictation.${extension}`;
}

function isTranscriptionResponse(
  value: unknown,
): value is { text: string; language?: string | null; emotion?: string | null } {
  return (
    typeof value === "object" &&
    value !== null &&
    "text" in value &&
    typeof value.text === "string" &&
    value.text.trim().length > 0
  );
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
  return "语音识别服务拒绝了本次请求。";
}
