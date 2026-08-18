import { describe, expect, it } from "vitest";

import {
  base64Pcm16ToFloat32,
  bytesToBase64,
  calculateAudioVolume,
  Pcm16Resampler,
  PcmByteChunker,
} from "@/features/chat/runtime/pcm-audio";

describe("Pcm16Resampler", () => {
  it("把 48kHz 浮点音频持续降采样为 16kHz PCM16", () => {
    const input = Float32Array.from(
      { length: 480 },
      (_, index) => Math.sin((index / 480) * Math.PI * 2) * 0.5,
    );
    const resampler = new Pcm16Resampler(48_000);

    const output = resampler.push(input);

    expect(output).toHaveLength(160);
    expect(Math.max(...output)).toBeGreaterThan(16_000);
    expect(Math.min(...output)).toBeLessThan(-16_000);
  });
});

describe("PcmByteChunker", () => {
  it("按 20ms 边界累积小型 AudioWorklet 输出", () => {
    const chunker = new PcmByteChunker(640);

    expect(chunker.push(new Int16Array(160))).toEqual([]);
    const chunks = chunker.push(new Int16Array(160));

    expect(chunks).toHaveLength(1);
    expect(chunks[0]).toHaveLength(640);
  });

  it("明确使用百炼 PCM 要求的小端字节序", () => {
    const chunks = new PcmByteChunker(4).push(Int16Array.from([0x1234, -2]));

    expect(Array.from(chunks[0] ?? [])).toEqual([0x34, 0x12, 0xfe, 0xff]);
  });
});

describe("PCM 编解码", () => {
  it("按小端序解码百炼返回的 PCM16 并计算可视音量", () => {
    const bytes = Uint8Array.from([0, 64, 0, 192]);
    const samples = base64Pcm16ToFloat32(bytesToBase64(bytes));

    expect(Array.from(samples)).toEqual([0.5, -0.5]);
    expect(calculateAudioVolume(samples)).toBe(1);
  });
});
