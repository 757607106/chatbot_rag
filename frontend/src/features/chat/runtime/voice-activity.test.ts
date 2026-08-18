import { describe, expect, it } from "vitest";

import {
  calculateSpeechThreshold,
  calculateVisualVolume,
  measureVoiceLevel,
} from "@/features/chat/runtime/voice-activity";

describe("语音活动检测", () => {
  it("静音采样返回零电平", () => {
    expect(measureVoiceLevel(new Float32Array(128))).toBe(0);
  });

  it("较轻的语音采样仍能越过安静环境阈值", () => {
    const samples = new Float32Array(128);
    for (let index = 0; index < samples.length; index += 1) {
      samples[index] = index % 2 === 0 ? 0.005 : -0.005;
    }
    const level = measureVoiceLevel(samples);

    expect(level).toBeGreaterThan(calculateSpeechThreshold(0.001));
  });

  it("噪声较高时提高阈值但保持上限", () => {
    expect(calculateSpeechThreshold(0)).toBe(0.0025);
    expect(calculateSpeechThreshold(0.01)).toBeCloseTo(0.0232);
    expect(calculateSpeechThreshold(0.1)).toBe(0.025);
  });

  it("低音量语音会被放大为可见动画幅度", () => {
    expect(calculateVisualVolume(0.012, 0.002)).toBeGreaterThan(0.3);
    expect(calculateVisualVolume(1, 0)).toBe(1);
  });
});
