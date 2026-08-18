import {
  createVoiceSession,
  type RealtimeVoiceAdapter,
  type VoiceSessionControls,
  type VoiceSessionHelpers,
} from "@assistant-ui/react";

import { getAudioInputErrorMessage } from "@/features/chat/runtime/audio-input-error";
import {
  bytesToBase64,
  calculateAudioVolume,
  Pcm16Resampler,
  PcmByteChunker,
} from "@/features/chat/runtime/pcm-audio";
import { PcmPlaybackQueue } from "@/features/chat/runtime/pcm-playback-queue";
import {
  getRealtimeVoiceUrl,
  parseRealtimeVoiceServerEvent,
} from "@/features/chat/runtime/realtime-voice-protocol";
import {
  type VoiceTranscriptRecord,
  VoiceTranscriptLedger,
} from "@/features/chat/runtime/voice-transcript";

type ServerVoiceAdapterOptions = {
  onError?: (message: string) => void;
  onConversationEnd?: (records: readonly VoiceTranscriptRecord[]) => void;
};

const SESSION_START_TIMEOUT_MS = 10_000;

export function isServerVoiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof AudioContext !== "undefined" &&
    typeof AudioWorkletNode !== "undefined" &&
    typeof WebSocket !== "undefined"
  );
}

export class ServerVoiceAdapter implements RealtimeVoiceAdapter {
  constructor(private readonly options: ServerVoiceAdapterOptions = {}) {}

  connect(options: { abortSignal?: AbortSignal }): RealtimeVoiceAdapter.Session {
    return createVoiceSession(options, async (helpers) => {
      try {
        return await this.setup(helpers);
      } catch (error) {
        this.options.onError?.(getAudioInputErrorMessage(error));
        throw error;
      }
    });
  }

  private async setup(helpers: VoiceSessionHelpers): Promise<VoiceSessionControls> {
    if (!isServerVoiceSupported()) {
      throw new Error(
        typeof window !== "undefined" && !window.isSecureContext
          ? "实时语音需要 HTTPS；在运行服务的本机调试时也可使用 localhost。"
          : "当前浏览器不支持实时语音，请使用最新版 Chrome、Edge 或 Safari。",
      );
    }

    const websocketUrl = getRealtimeVoiceUrl();
    const audioContext = new AudioContext();
    let stream: MediaStream;
    try {
      await audioContext.resume();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      await audioContext.audioWorklet.addModule("/pcm-capture-worklet.js");
    } catch (error) {
      void audioContext.close();
      throw error;
    }

    const inputSource = audioContext.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(audioContext, "pcm-capture");
    const silentOutput = audioContext.createGain();
    silentOutput.gain.value = 0;
    inputSource.connect(worklet);
    worklet.connect(silentOutput);
    silentOutput.connect(audioContext.destination);

    const websocket = new WebSocket(websocketUrl);
    const resampler = new Pcm16Resampler(audioContext.sampleRate);
    const chunker = new PcmByteChunker();
    const playback = new PcmPlaybackQueue(audioContext);
    const transcriptLedger = new VoiceTranscriptLedger();
    let disposed = false;
    let muted = false;
    let ready = false;
    let currentMode: "listening" | "speaking" = "listening";
    let assistantTranscript = "";
    let startTimeout: number | undefined;

    const emitMode = (mode: "listening" | "speaking"): void => {
      currentMode = mode;
      helpers.emitMode(mode);
    };

    const cleanup = (): void => {
      if (disposed) return;
      disposed = true;
      ready = false;
      if (startTimeout !== undefined) window.clearTimeout(startTimeout);
      helpers.emitVolume(0);
      playback.clear();
      worklet.port.onmessage = null;
      inputSource.disconnect();
      worklet.disconnect();
      silentOutput.disconnect();
      for (const track of stream.getTracks()) track.stop();
      if (websocket.readyState === WebSocket.CONNECTING) {
        websocket.addEventListener("open", () => websocket.close(1000), {
          once: true,
        });
      } else if (websocket.readyState === WebSocket.OPEN) {
        websocket.close(1000);
      }
      void audioContext.close();
      const records = transcriptLedger.snapshot();
      if (records.length > 0) {
        try {
          this.options.onConversationEnd?.(records);
        } catch (error) {
          console.warn("实时语音文字记录写入失败", error);
          this.options.onError?.("语音已结束，但文字记录保存失败。");
        }
      }
    };

    let resolveReady: () => void = () => undefined;
    let rejectReady: (error: Error) => void = () => undefined;
    const readyPromise = new Promise<void>((resolve, reject) => {
      resolveReady = resolve;
      rejectReady = reject;
    });
    startTimeout = window.setTimeout(() => {
      rejectReady(new Error("实时语音连接超时，请稍后重试。"));
    }, SESSION_START_TIMEOUT_MS);

    const fail = (error: unknown): void => {
      const normalized = error instanceof Error ? error : new Error("实时语音连接异常。");
      if (!ready) {
        rejectReady(normalized);
        return;
      }
      if (disposed) return;
      console.warn("实时语音会话失败", normalized);
      this.options.onError?.(getAudioInputErrorMessage(normalized));
      helpers.end("error", normalized);
      cleanup();
    };

    websocket.addEventListener("message", (message) => {
      if (disposed) return;
      if (typeof message.data !== "string") {
        fail(new Error("实时语音服务返回了非文本事件。"));
        return;
      }
      try {
        const event = parseRealtimeVoiceServerEvent(message.data);
        switch (event.type) {
          case "session.ready":
            if (!ready) {
              ready = true;
              window.clearTimeout(startTimeout);
              resolveReady();
            }
            break;
          case "input.speech_started":
            transcriptLedger.finishAssistant();
            playback.clear();
            assistantTranscript = "";
            emitMode("listening");
            break;
          case "input.speech_stopped":
            helpers.emitVolume(0);
            emitMode("speaking");
            break;
          case "transcript.user.delta":
            helpers.emitTranscript({
              role: "user",
              text: `${event.text}${event.stash}`,
              isFinal: false,
            });
            break;
          case "transcript.user.done":
            transcriptLedger.addUserFinal(event.transcript);
            helpers.emitTranscript({
              role: "user",
              text: event.transcript,
              isFinal: true,
            });
            break;
          case "transcript.assistant.delta":
            assistantTranscript += event.delta;
            transcriptLedger.updateAssistantDraft(assistantTranscript);
            helpers.emitTranscript({
              role: "assistant",
              text: assistantTranscript,
              isFinal: false,
            });
            break;
          case "transcript.assistant.done":
            assistantTranscript = event.transcript;
            transcriptLedger.finishAssistant(event.transcript);
            helpers.emitTranscript({
              role: "assistant",
              text: event.transcript,
              isFinal: true,
            });
            break;
          case "audio.delta":
            emitMode("speaking");
            helpers.emitVolume(playback.enqueue(event.audio));
            break;
          case "tool.started":
            emitMode("speaking");
            break;
          case "tool.completed":
            break;
          case "response.done":
            transcriptLedger.finishAssistant();
            assistantTranscript = "";
            helpers.emitVolume(0);
            emitMode("listening");
            break;
          case "error":
            fail(new Error(event.message));
            break;
        }
      } catch (error) {
        fail(error);
      }
    });
    websocket.addEventListener("error", () => {
      if (disposed) return;
      fail(new Error("无法连接实时语音服务，请稍后重试。"));
    });
    websocket.addEventListener("close", () => {
      if (!disposed) fail(new Error("实时语音连接已中断，请重试。"));
    });

    worklet.port.onmessage = (event: MessageEvent<unknown>): void => {
      if (!ready || muted || websocket.readyState !== WebSocket.OPEN) return;
      if (!(event.data instanceof Float32Array)) return;
      if (currentMode === "listening") {
        helpers.emitVolume(calculateAudioVolume(event.data));
      }
      for (const chunk of chunker.push(resampler.push(event.data))) {
        websocket.send(
          JSON.stringify({
            type: "audio.append",
            audio: bytesToBase64(chunk),
          }),
        );
      }
    };

    try {
      await readyPromise;
    } catch (error) {
      window.clearTimeout(startTimeout);
      cleanup();
      throw error;
    }
    helpers.setStatus({ type: "running" });
    emitMode("listening");

    return {
      disconnect: cleanup,
      mute: () => {
        muted = true;
        helpers.emitVolume(0);
        for (const track of stream.getAudioTracks()) track.enabled = false;
      },
      unmute: () => {
        muted = false;
        for (const track of stream.getAudioTracks()) track.enabled = true;
        void audioContext.resume();
      },
    };
  }
}
