# ADR 008：服务端语音识别与 Agent Voice Mode

> 状态：已被 ADR 009 取代。

该方案的分段 ASR、文本 Agent、分段 TTS、输入框听写和消息朗读代码已删除，不再作为
兼容路径保留。当前实现见 `009-qwen-audio-realtime-voice.md`。

## 背景

聊天输入需要可靠的中文语音识别，并提供不必反复点击发送和朗读的 Voice Mode。浏览器
原生 `SpeechRecognition` 的支持范围、识别模型和权限行为不可控；如果前端直接连接模型，
会暴露百炼 Key。Voice Mode 的回答还必须继续经过既有 AgentScope Agent，保留 RAG、
MCP 工具允许列表、系统提示词和公共流式协议。

## 备选方案

1. 使用浏览器 `SpeechRecognition` 和 `speechSynthesis` 完成全部语音交互。
2. 浏览器直连 Qwen-Audio 实时接口，单独维护一条语音对话链路。
3. 服务端使用 Qwen3 ASR，前端通过 VAD 自动分轮，再复用现有 Agent 流式聊天和服务端
   Qwen TTS。

方案一依赖浏览器实现，无法保证模型和中文识别一致性。方案二虽然能降低音频链路延迟，
但会绕过当前 Agent/RAG/MCP 编排，并需要在浏览器处理临时凭据和另一套会话状态。

## 决策

采用方案三：

- `models/asr_factory.py` 使用 DashScope `MultiModalConversation` 调用
  `qwen3-asr-flash`，将经过 MIME 和 10 MB 限制校验的短音频编码为 Data URL；
  `SpeechRecognitionService` 与 `POST /api/v1/speech/transcriptions` 提供协议无关和
  HTTP 边界。模型、语言分别由 `CHATBOT_ASR_MODEL`、`CHATBOT_ASR_LANGUAGE` 配置，
  Key 统一读取服务端 `DASHSCOPE_API_KEY`。
- assistant-ui `DictationAdapter` 使用 `MediaRecorder` 采集音频，停止录音后经同源 BFF
  转写，并把最终文本写入 Composer，用户确认后再发送。
- assistant-ui `RealtimeVoiceAdapter` 使用 Web Audio 音量分析做前端 VAD；检测到说话后
  约 900ms 静音或达到 30 秒上限即提交本轮。转写文本调用既有 `ChatModelAdapter`，
  因此继续走相同 Agent、RAG 和 MCP，再调用 ADR 007 的 TTS 服务播放回答并恢复监听。
- 麦克风仅在 `localhost` 或 HTTPS 安全上下文中启用。断开、静音或取消必须停止媒体轨、
  音频播放、动画帧和进行中的 HTTP 请求；权限和服务错误转换为中文公开文案。

## 影响与后续约束

- 当前 Voice Mode 是 VAD 驱动的自动轮次语音对话，不建立绕过 Agent 的模型直连；相较
  模型原生音频到音频会增加 ASR、Agent 和 TTS 三段延迟。
- 单次 Voice Mode 连接中的文本历史保存在浏览器内存，结束或刷新后不持久化；如需跨端
  恢复，必须与服务端线程状态一起独立设计。
- 调整 VAD 阈值、静音窗口、单轮时长或增加播放期间打断能力时，必须补充嘈杂环境、弱音、
  连续说话、取消和媒体资源释放回归。
