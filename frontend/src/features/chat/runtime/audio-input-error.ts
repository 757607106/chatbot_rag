export function getAudioInputErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "请在浏览器地址栏中允许本网站使用麦克风。";
    }
    if (error.name === "NotFoundError") {
      return "没有检测到可用的麦克风。";
    }
    if (error.name === "NotReadableError") {
      return "麦克风正被其他应用占用，请关闭占用后重试。";
    }
  }
  return error instanceof Error ? error.message : "麦克风启动失败，请重试。";
}
