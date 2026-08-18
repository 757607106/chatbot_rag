import {
  createVoiceSession,
  type RealtimeVoiceAdapter,
  type VoiceSessionControls,
  type VoiceSessionHelpers,
} from "@assistant-ui/react";

import { transcribeSpeech } from "@/features/chat/api/asr-client";
import { synthesizeSpeech } from "@/features/chat/api/tts-client";
import { getAudioInputErrorMessage } from "@/features/chat/runtime/audio-input-error";
import {
  streamAssistantReply,
  type ChatInputMessage,
} from "@/features/chat/runtime/chat-model-adapter";
import {
  calculateSpeechThreshold,
  calculateVisualVolume,
  measureVoiceLevel,
} from "@/features/chat/runtime/voice-activity";

type ServerVoiceAdapterOptions = {
  onError?: (message: string) => void;
};

const PREFERRED_MEDIA_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
] as const;
const END_OF_TURN_SILENCE_MS = 900;
const MAX_RECORDING_MS = 30_000;
const SPEECH_CONFIRMATION_MS = 80;
const MAX_VOLUME_FRAME_MS = 50;

export function isServerVoiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof MediaRecorder !== "undefined" &&
    typeof AudioContext !== "undefined"
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
          ? "语音模式需要 HTTPS；在运行服务的本机调试时也可使用 localhost。"
          : "当前浏览器不支持语音模式，请使用最新版 Chrome、Edge 或 Safari。",
      );
    }

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
    } catch (error) {
      void audioContext.close();
      throw error;
    }
    const inputSource = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.35;
    const silentOutput = audioContext.createGain();
    silentOutput.gain.value = 0;
    inputSource.connect(analyser);
    analyser.connect(silentOutput);
    silentOutput.connect(audioContext.destination);
    await audioContext.resume();

    const samples = new Float32Array(analyser.fftSize);
    const conversation: ChatInputMessage[] = [];
    let recorder: MediaRecorder | null = null;
    let animationFrame: number | null = null;
    let activeRequest: AbortController | null = null;
    let playbackSource: AudioBufferSourceNode | null = null;
    let resolvePlayback: (() => void) | null = null;
    let disposed = false;
    let muted = false;
    let busy = false;
    let discardRecording = false;

    const stopAnimation = (): void => {
      if (animationFrame !== null) cancelAnimationFrame(animationFrame);
      animationFrame = null;
      helpers.emitVolume(0);
    };

    const stopPlayback = (): void => {
      if (playbackSource !== null) {
        playbackSource.onended = null;
        try {
          playbackSource.stop();
        } catch {
          // 已自然结束的 AudioBufferSourceNode 无需再次停止。
        }
        playbackSource.disconnect();
        playbackSource = null;
      }
      const finishPlayback = resolvePlayback;
      resolvePlayback = null;
      finishPlayback?.();
    };

    const dispose = (): void => {
      if (disposed) return;
      disposed = true;
      discardRecording = true;
      stopAnimation();
      activeRequest?.abort();
      activeRequest = null;
      stopPlayback();
      if (recorder?.state === "recording") recorder.stop();
      recorder = null;
      inputSource.disconnect();
      analyser.disconnect();
      silentOutput.disconnect();
      for (const track of stream.getTracks()) track.stop();
      void audioContext.close();
    };

    const fail = (error: unknown): void => {
      if (disposed) return;
      const message = getAudioInputErrorMessage(error);
      console.warn("语音模式运行失败", error);
      this.options.onError?.(message);
      helpers.end("error", error);
      dispose();
    };

    const playAudio = async (audio: ArrayBuffer): Promise<void> => {
      await audioContext.resume();
      const decoded = await audioContext.decodeAudioData(audio.slice(0));
      if (disposed) return;
      await new Promise<void>((resolve) => {
        const source = audioContext.createBufferSource();
        source.buffer = decoded;
        source.connect(audioContext.destination);
        playbackSource = source;
        resolvePlayback = resolve;
        source.onended = () => {
          source.disconnect();
          if (playbackSource === source) playbackSource = null;
          resolvePlayback = null;
          resolve();
        };
        source.start();
      });
    };

    const runAgentTurn = async (blob: Blob): Promise<void> => {
      const controller = new AbortController();
      activeRequest = controller;
      try {
        helpers.emitMode("speaking");
        helpers.emitVolume(0);
        const transcription = await transcribeSpeech(blob, controller.signal);
        if (disposed) return;
        const userTurn: ChatInputMessage = { role: "user", content: transcription.text };
        conversation.push(userTurn);
        helpers.emitTranscript({ role: "user", text: transcription.text, isFinal: true });

        let assistantText = "";
        for await (const update of streamAssistantReply(conversation, controller.signal)) {
          const nextText = (update.content ?? [])
            .filter((part) => part.type === "text")
            .map((part) => part.text)
            .join("\n")
            .trim();
          if (!nextText || nextText === assistantText) continue;
          assistantText = nextText;
          helpers.emitTranscript({ role: "assistant", text: assistantText, isFinal: false });
        }
        if (!assistantText) throw new Error("Agent 没有返回可朗读的文本回复。");
        conversation.push({ role: "assistant", content: assistantText });
        helpers.emitTranscript({ role: "assistant", text: assistantText, isFinal: true });

        const audio = await synthesizeSpeech(assistantText, controller.signal);
        if (!disposed) await playAudio(audio);
      } finally {
        if (activeRequest === controller) activeRequest = null;
      }
    };

    const selectMediaType = (): string | undefined =>
      PREFERRED_MEDIA_TYPES.find((type) => MediaRecorder.isTypeSupported(type));

    const startListeningTurn = (): void => {
      if (disposed || muted || busy) return;
      busy = true;
      discardRecording = false;
      const chunks: BlobPart[] = [];
      const mediaType = selectMediaType();
      recorder = mediaType
        ? new MediaRecorder(stream, { mimeType: mediaType })
        : new MediaRecorder(stream);
      const currentRecorder = recorder;
      let detectedSpeech = false;
      let lastSpeechAt = 0;
      let speechEvidenceMs = 0;
      let noiseFloor: number | null = null;
      const startedAt = performance.now();
      let previousVolumeAt = startedAt;

      currentRecorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      });
      currentRecorder.addEventListener("error", (event) => fail(event), { once: true });
      currentRecorder.addEventListener(
        "stop",
        () => {
          stopAnimation();
          recorder = null;
          const shouldDiscard = discardRecording || !detectedSpeech;
          if (shouldDiscard) {
            busy = false;
            if (!disposed && !muted) startListeningTurn();
            return;
          }
          const blob = new Blob(chunks, {
            type: currentRecorder.mimeType || "audio/webm",
          });
          void runAgentTurn(blob)
            .then(() => {
              busy = false;
              if (!disposed && !muted) {
                helpers.emitMode("listening");
                startListeningTurn();
              }
            })
            .catch(fail);
        },
        { once: true },
      );
      currentRecorder.start(250);
      helpers.emitMode("listening");

      const monitorVolume = (): void => {
        if (disposed || muted || currentRecorder.state !== "recording") return;
        if (audioContext.state === "suspended") void audioContext.resume();
        analyser.getFloatTimeDomainData(samples);
        const level = measureVoiceLevel(samples);
        const now = performance.now();
        const frameDuration = Math.min(MAX_VOLUME_FRAME_MS, now - previousVolumeAt);
        previousVolumeAt = now;

        if (noiseFloor === null) noiseFloor = Math.min(level, 0.002);
        const speechThreshold = calculateSpeechThreshold(noiseFloor);
        const isAboveThreshold = level >= speechThreshold;
        helpers.emitVolume(calculateVisualVolume(level, noiseFloor));

        if (isAboveThreshold) {
          speechEvidenceMs = Math.min(SPEECH_CONFIRMATION_MS, speechEvidenceMs + frameDuration);
          if (speechEvidenceMs >= SPEECH_CONFIRMATION_MS) detectedSpeech = true;
        } else {
          speechEvidenceMs = Math.max(0, speechEvidenceMs - frameDuration * 0.35);
          if (!detectedSpeech) noiseFloor = noiseFloor * 0.97 + level * 0.03;
        }
        if (detectedSpeech && level >= speechThreshold * 0.55) {
          lastSpeechAt = now;
        }
        const reachedEndOfTurn = detectedSpeech && now - lastSpeechAt >= END_OF_TURN_SILENCE_MS;
        const reachedRecordingLimit = now - startedAt >= MAX_RECORDING_MS;
        if (reachedEndOfTurn || reachedRecordingLimit) {
          discardRecording = !detectedSpeech;
          currentRecorder.stop();
          return;
        }
        animationFrame = requestAnimationFrame(monitorVolume);
      };
      animationFrame = requestAnimationFrame(monitorVolume);
    };

    helpers.setStatus({ type: "running" });
    helpers.emitMode("listening");
    startListeningTurn();

    return {
      disconnect: dispose,
      mute: () => {
        muted = true;
        for (const track of stream.getAudioTracks()) track.enabled = false;
        if (recorder?.state === "recording") {
          discardRecording = true;
          recorder.stop();
        }
      },
      unmute: () => {
        muted = false;
        for (const track of stream.getAudioTracks()) track.enabled = true;
        void audioContext.resume();
        if (!busy) startListeningTurn();
      },
    };
  }
}
