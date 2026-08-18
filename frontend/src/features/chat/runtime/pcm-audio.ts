const PCM16_MIN = -32_768;
const PCM16_MAX = 32_767;

export class Pcm16Resampler {
  private readonly ratio: number;
  private tail = new Float32Array(0);
  private position = 0;

  constructor(inputSampleRate: number, outputSampleRate = 16_000) {
    if (
      !Number.isFinite(inputSampleRate) ||
      !Number.isFinite(outputSampleRate) ||
      inputSampleRate < outputSampleRate ||
      outputSampleRate <= 0
    ) {
      throw new Error("音频采样率无效。");
    }
    this.ratio = inputSampleRate / outputSampleRate;
  }

  push(input: Float32Array): Int16Array {
    if (input.length === 0) return new Int16Array(0);
    const merged = new Float32Array(this.tail.length + input.length);
    merged.set(this.tail);
    merged.set(input, this.tail.length);

    const output: number[] = [];
    while (this.position + 1 < merged.length) {
      const leftIndex = Math.floor(this.position);
      const fraction = this.position - leftIndex;
      const left = merged[leftIndex] ?? 0;
      const right = merged[leftIndex + 1] ?? left;
      output.push(floatToPcm16(left + (right - left) * fraction));
      this.position += this.ratio;
    }

    const consumed = Math.min(Math.floor(this.position), merged.length);
    this.tail = merged.slice(consumed);
    this.position -= consumed;
    return Int16Array.from(output);
  }
}

export class PcmByteChunker {
  private pending = new Uint8Array(0);

  constructor(private readonly chunkBytes = 640) {
    if (chunkBytes <= 0 || chunkBytes % 2 !== 0) {
      throw new Error("PCM 分帧字节数必须是正偶数。");
    }
  }

  push(samples: Int16Array): Uint8Array[] {
    const incoming = new Uint8Array(samples.length * 2);
    const incomingView = new DataView(incoming.buffer);
    for (let index = 0; index < samples.length; index += 1) {
      incomingView.setInt16(index * 2, samples[index] ?? 0, true);
    }
    const merged = new Uint8Array(this.pending.length + incoming.length);
    merged.set(this.pending);
    merged.set(incoming, this.pending.length);

    const chunks: Uint8Array[] = [];
    let offset = 0;
    while (offset + this.chunkBytes <= merged.length) {
      chunks.push(merged.slice(offset, offset + this.chunkBytes));
      offset += this.chunkBytes;
    }
    this.pending = merged.slice(offset);
    return chunks;
  }
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index] ?? 0);
  }
  return btoa(binary);
}

export function base64Pcm16ToFloat32(value: string): Float32Array {
  const binary = atob(value);
  if (binary.length === 0 || binary.length % 2 !== 0) {
    throw new Error("服务端返回了无效的 PCM16 音频。");
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const view = new DataView(bytes.buffer);
  const samples = new Float32Array(bytes.length / 2);
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true) / 32_768;
  }
  return samples;
}

export function calculateAudioVolume(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let energy = 0;
  for (const sample of samples) energy += sample * sample;
  return Math.min(1, Math.sqrt(energy / samples.length) * 5);
}

function floatToPcm16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return clamped < 0 ? Math.round(clamped * -PCM16_MIN) : Math.round(clamped * PCM16_MAX);
}
