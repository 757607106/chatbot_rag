import type { DictationAdapter } from "@assistant-ui/react";

import { transcribeSpeech } from "@/features/chat/api/asr-client";
import { getAudioInputErrorMessage } from "@/features/chat/runtime/audio-input-error";

type ServerDictationAdapterOptions = {
  onStart?: () => void;
  onError?: (message: string) => void;
};

const PREFERRED_MEDIA_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
] as const;

export function isServerDictationSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof MediaRecorder !== "undefined"
  );
}

export class ServerDictationAdapter implements DictationAdapter {
  readonly disableInputDuringDictation = true;

  constructor(private readonly options: ServerDictationAdapterOptions = {}) {}

  listen(): DictationAdapter.Session {
    const speechStartCallbacks = new Set<() => void>();
    const speechCallbacks = new Set<(result: DictationAdapter.Result) => void>();
    const speechEndCallbacks = new Set<(result: DictationAdapter.Result) => void>();
    const chunks: BlobPart[] = [];
    const requestController = new AbortController();
    let recorder: MediaRecorder | null = null;
    let stream: MediaStream | null = null;
    let stopRequested = false;
    let cancelled = false;
    let settled = false;
    let resolveCompletion: () => void = () => undefined;
    const completion = new Promise<void>((resolve) => {
      resolveCompletion = resolve;
    });

    const session: DictationAdapter.Session = {
      status: { type: "starting" },
      stop: async () => {
        stopRequested = true;
        if (recorder?.state === "recording") recorder.stop();
        await completion;
      },
      cancel: () => {
        cancelled = true;
        requestController.abort();
        if (recorder?.state === "recording") recorder.stop();
        finish({ type: "ended", reason: "cancelled" });
      },
      onSpeechStart: (callback) => {
        speechStartCallbacks.add(callback);
        return () => speechStartCallbacks.delete(callback);
      },
      onSpeech: (callback) => {
        speechCallbacks.add(callback);
        return () => speechCallbacks.delete(callback);
      },
      onSpeechEnd: (callback) => {
        speechEndCallbacks.add(callback);
        return () => speechEndCallbacks.delete(callback);
      },
    };

    function cleanup(): void {
      for (const track of stream?.getTracks() ?? []) track.stop();
      stream = null;
    }

    function finish(status: DictationAdapter.Status): void {
      if (settled) return;
      settled = true;
      session.status = status;
      cleanup();
      resolveCompletion();
    }

    const fail = (error: unknown): void => {
      console.warn("服务端语音识别失败", error);
      const message = getAudioInputErrorMessage(error);
      this.options.onError?.(message);
      finish({ type: "ended", reason: "error" });
    };

    const finalizeRecording = async (): Promise<void> => {
      if (cancelled || settled) {
        finish({ type: "ended", reason: "cancelled" });
        return;
      }
      try {
        const mimeType = recorder?.mimeType || "audio/webm";
        const result = await transcribeSpeech(
          new Blob(chunks, { type: mimeType }),
          requestController.signal,
        );
        const transcript = { transcript: result.text, isFinal: true };
        for (const callback of speechCallbacks) callback(transcript);
        for (const callback of speechEndCallbacks) callback(transcript);
        finish({ type: "ended", reason: "stopped" });
      } catch (error) {
        if (cancelled || requestController.signal.aborted) {
          finish({ type: "ended", reason: "cancelled" });
          return;
        }
        fail(error);
      }
    };

    const startRecording = async (): Promise<void> => {
      try {
        if (!isServerDictationSupported()) {
          throw new Error(
            typeof window !== "undefined" && !window.isSecureContext
              ? "语音输入需要 HTTPS；在运行服务的本机调试时也可使用 localhost。"
              : "当前浏览器不支持录音，请使用最新版 Chrome、Edge 或 Safari。",
          );
        }
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
          },
        });
        if (cancelled || settled) {
          cleanup();
          return;
        }
        const mediaType = PREFERRED_MEDIA_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
        recorder = mediaType
          ? new MediaRecorder(stream, { mimeType: mediaType })
          : new MediaRecorder(stream);
        recorder.addEventListener("dataavailable", (event) => {
          if (event.data.size > 0) chunks.push(event.data);
        });
        recorder.addEventListener("stop", () => void finalizeRecording(), { once: true });
        recorder.addEventListener("error", (event) => fail(event), { once: true });
        recorder.start(250);
        session.status = { type: "running" };
        this.options.onStart?.();
        for (const callback of speechStartCallbacks) callback();
        if (stopRequested) recorder.stop();
      } catch (error) {
        fail(error);
      }
    };

    void startRecording();
    return session;
  }
}
