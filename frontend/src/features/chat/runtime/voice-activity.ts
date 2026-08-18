/** 根据浮点时域采样计算兼顾持续语音与短促辅音的输入电平。 */
export function measureVoiceLevel(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let squareSum = 0;
  let peak = 0;
  for (const sample of samples) {
    const normalized = Math.abs(sample);
    squareSum += normalized * normalized;
    peak = Math.max(peak, normalized);
  }
  const rootMeanSquare = Math.sqrt(squareSum / samples.length);
  return Math.max(rootMeanSquare, peak * 0.22);
}

/** 根据环境噪声底线计算语音触发阈值，避免固定门限漏掉较轻的说话声。 */
export function calculateSpeechThreshold(noiseFloor: number): number {
  return Math.min(0.025, Math.max(0.0025, noiseFloor * 2.2 + 0.0012));
}

/** 把较小的真实麦克风电平映射为气泡可感知的动画幅度。 */
export function calculateVisualVolume(level: number, noiseFloor: number): number {
  return Math.min(1, Math.max(0, (level - noiseFloor) * 28 + level * 6));
}
