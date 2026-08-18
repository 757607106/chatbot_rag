import { base64Pcm16ToFloat32, calculateAudioVolume } from "@/features/chat/runtime/pcm-audio";

const OUTPUT_SAMPLE_RATE = 24_000;

export class PcmPlaybackQueue {
  private readonly sources = new Set<AudioBufferSourceNode>();
  private nextStartTime = 0;

  constructor(private readonly audioContext: AudioContext) {}

  enqueue(base64Audio: string): number {
    const samples = base64Pcm16ToFloat32(base64Audio);
    const buffer = this.audioContext.createBuffer(1, samples.length, OUTPUT_SAMPLE_RATE);
    buffer.copyToChannel(new Float32Array(samples), 0);
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);
    source.addEventListener(
      "ended",
      () => {
        source.disconnect();
        this.sources.delete(source);
      },
      { once: true },
    );
    const startTime = Math.max(this.audioContext.currentTime + 0.02, this.nextStartTime);
    source.start(startTime);
    this.nextStartTime = startTime + buffer.duration;
    this.sources.add(source);
    return calculateAudioVolume(samples);
  }

  clear(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // 已经自然结束的音频节点不需要再次停止。
      }
      source.disconnect();
    }
    this.sources.clear();
    this.nextStartTime = this.audioContext.currentTime;
  }
}
