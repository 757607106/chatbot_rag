/** 服务端百炼语音识别客户端边界。 */

const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

export type SpeechTranscription = {
  text: string;
  language: string | null;
  emotion: string | null;
};

export class SpeechRecognitionRequestError extends Error {
  constructor(message = "录音格式无效。") {
    super(message);
    this.name = "SpeechRecognitionRequestError";
  }
}

export class SpeechRecognitionServiceError extends Error {
  constructor(message = "语音识别失败，请稍后重试。") {
    super(message);
    this.name = "SpeechRecognitionServiceError";
  }
}

export async function transcribeSpeech(
  audio: Blob,
  signal?: AbortSignal,
): Promise<SpeechTranscription> {
  if (audio.size === 0) throw new SpeechRecognitionRequestError("没有录到声音，请重试。");
  if (audio.size > MAX_AUDIO_BYTES) {
    throw new SpeechRecognitionRequestError("单次录音不能超过 10MB。");
  }
  const mediaType = audio.type.split(";", 1)[0]?.toLowerCase() ?? "";
  if (!mediaType.startsWith("audio/")) {
    throw new SpeechRecognitionRequestError();
  }

  const body = new FormData();
  body.append("file", audio, `dictation.${mediaType === "audio/mp4" ? "m4a" : "webm"}`);

  let response: Response;
  try {
    response = await fetch("/api/speech/transcriptions", {
      method: "POST",
      body,
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SpeechRecognitionServiceError("无法连接语音识别服务，请稍后重试。");
  }

  if (!response.ok) {
    if ([400, 413, 415, 422].includes(response.status)) {
      throw new SpeechRecognitionRequestError(await readErrorDetail(response));
    }
    throw new SpeechRecognitionServiceError(await readErrorDetail(response));
  }

  const value: unknown = await response.json();
  if (!isTranscription(value)) {
    throw new SpeechRecognitionServiceError("语音服务返回了无效的识别结果。");
  }
  return {
    text: value.text.trim(),
    language: typeof value.language === "string" ? value.language : null,
    emotion: typeof value.emotion === "string" ? value.emotion : null,
  };
}

async function readErrorDetail(response: Response): Promise<string> {
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
    // 非 JSON 错误响应使用调用方提供的默认错误类型。
  }
  return response.status >= 500 ? "语音识别失败，请稍后重试。" : "录音格式无效。";
}

function isTranscription(
  value: unknown,
): value is { text: string; language?: unknown; emotion?: unknown } {
  return (
    typeof value === "object" &&
    value !== null &&
    "text" in value &&
    typeof value.text === "string" &&
    value.text.trim().length > 0
  );
}
