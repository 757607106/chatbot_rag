/** 服务端语音合成（TTS）客户端边界：只处理请求、错误分类与取消。 */

export class SpeechSynthesisRequestError extends Error {
  constructor(message = "语音合成请求无效。") {
    super(message);
    this.name = "SpeechSynthesisRequestError";
  }
}

export class SpeechSynthesisServiceError extends Error {
  constructor(message = "语音合成失败，请稍后重试。") {
    super(message);
    this.name = "SpeechSynthesisServiceError";
  }
}

export async function synthesizeSpeech(text: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  let response: Response;
  try {
    response = await fetch("/api/speech/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SpeechSynthesisServiceError("无法连接语音服务，请稍后重试。");
  }

  if (!response.ok) {
    if (response.status === 422) {
      throw new SpeechSynthesisRequestError("待合成文本过长或格式无效。");
    }
    if (response.status === 503) {
      throw new SpeechSynthesisServiceError("语音合成服务暂不可用。");
    }
    throw new SpeechSynthesisServiceError();
  }

  const contentType = response.headers.get("content-type");
  if (contentType === null || !contentType.startsWith("audio/")) {
    throw new SpeechSynthesisServiceError("语音服务返回了无法播放的内容。");
  }

  return response.arrayBuffer();
}
