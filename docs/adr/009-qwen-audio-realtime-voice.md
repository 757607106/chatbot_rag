# ADR 009：单模型实时语音与知识库 Function Calling

> 状态：已接受。

## 背景

旧 Voice Mode 每轮依次等待浏览器判定约 900ms 静音、上传完整压缩录音、Qwen3 ASR
完成、文本 Agent/RAG 完成、Qwen TTS 生成完整 WAV，再下载并解码播放。各阶段无法重叠，
第一段声音只能在整条链路完成后出现；输入框听写和消息朗读又维护了另外两条相近路径。

目标是在不向浏览器暴露百炼 Key 的前提下，使用一个同时处理输入音频、转写、推理和输出
音频的模型，并让知识库问答继续执行 AgentScope 2.0.5 的官方 `search_knowledge` 工具。

实现依据固定为 [AgentScope 2.0.5 RAG 文档](https://docs.agentscope.io/versions/2.0.5/zh/building-blocks/rag)、
[Qwen-Audio Realtime WebSocket API](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api)、
[客户端事件](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events)和
[服务端事件](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events)。

## 备选方案

1. 调低旧浏览器 VAD 静音阈值并继续优化分段 ASR、文本 Agent 和完整 TTS。
2. 浏览器直连百炼 Realtime，使用长期或临时模型凭据。
3. 浏览器连接项目 WebSocket，由服务端持有百炼 Realtime 会话并把 Function Calling
   适配到 AgentScope `Toolkit`。

方案一只能减少局部等待，无法消除串行阶段和完整文件边界。方案二会把供应商协议与凭据
生命周期放入浏览器，也无法在可信边界内执行知识库。选择方案三。

## 决策

- 默认模型使用速度优先的 `qwen-audio-3.0-realtime-flash`，通过
  `CHATBOT_REALTIME_VOICE_MODEL` 可显式改为同协议模型；默认音色为 `longanqian`。
- `models/realtime_voice.py` 只负责创建带服务端 Authorization Header 的百炼 WebSocket；
  `RealtimeVoiceService` 负责浏览器公共事件、百炼事件和 AgentScope 工具结果之间的协议
  转换。项目不引入第二套智能体框架。
- 浏览器使用 `AudioWorklet` 获取浮点采样，持续降采样为 16kHz 单声道 PCM16，并按约
  20ms 分帧。百炼 24kHz PCM16 音频增量到达后立即排队播放，不再生成或下载完整 WAV。
- 会话使用 `smart_turn`，让声学与语义共同判断轮次；收到用户开始说话事件时立即停止
  本地待播音频，支持自然打断。
- assistant-ui 只负责在实时会话期间渲染临时 voice messages。项目使用
  `VoiceTranscriptLedger` 按轮次收集最终用户/助手转写，并保留断开前已经生成的助手文字；
  正常结束、手动结束或异常断开后，先清除临时消息，再通过公开
  `ThreadRuntime.export/import` 把记录原子接到当前基础分支。该导入不启动文本模型。
- 文本聊天和实时语音通过 `agents/knowledge_tools.py` 共用同一个
  `RAGMiddleware.Parameters(mode="agentic", top_k=...)` 装配函数。语音会话仅把该中间件
  `list_tools()` 返回的只读 `search_knowledge` 注册到模型；模型发起 Function Call 后，
  服务端使用 `Toolkit.call_tool` 和独立 `AgentState` 执行，再以标准
  `function_call_output` 写回，并在首轮 `response.done` 后触发一次二轮响应。
- 文本聊天仍由请求级 AgentScope Agent 编排，并继续支持配置的 MCP 工具。实时语音不
  自动复制 MCP 工具，特别是不暴露变更类业务操作；增加语音 MCP 必须另行设计权限、确认
  和审计。
- 浏览器协议只接受 `audio.append`。服务端校验 Base64、PCM16 对齐和 6400 字节单帧上限；
  输出只包含会话、语音、转写、音频、脱敏工具状态、完成和公开错误。百炼原始事件、工具
  名称、参数、检索证据和异常细节不进入浏览器。
- Python WebSocket 在接受前校验显式 Origin 允许列表。浏览器地址由
  `NEXT_PUBLIC_CHATBOT_VOICE_WS_URL` 显式提供；百炼端点必须使用 `wss`，生产环境优先使用
  业务空间专属域名。Origin 不是身份认证，公网部署必须在网关额外实施用户鉴权、连接数
  限制和调用频率限制。

## 删除与迁移

本变更直接删除以下旧能力，不保留兼容分支：

- `POST /api/v1/speech/transcriptions`、`POST /api/v1/speech/tts` 及 Next.js BFF；
- `asr_factory.py`、`tts_factory.py`、两个独立语音服务和旧语音 schema；
- assistant-ui `DictationAdapter`、输入框听写按钮、助手消息朗读按钮、浏览器 VAD 和
  `MediaRecorder` Voice Mode；
- `CHATBOT_ASR_*`、`CHATBOT_TTS_*` 与 `DASHSCOPE_WEBSOCKET_BASE_URL` 语音配置。

调用方必须改用 `WS /api/v1/voice/realtime` 和新的实时语音配置。普通文本聊天 API 不变。

## 影响与约束

- 语音模型自身维护一次 WebSocket 连接内的对话历史，连接结束后项目不持久化语音线程。
- 文字转写会在连接结束后保留到页面级 `LocalRuntime`，可作为后续文本请求的显式历史；
  页面刷新、跨设备恢复和服务端审计仍不在本决策范围内。
- 知识库检索仍会产生向量召回和重排耗时，但不再额外串联独立文本生成模型和完整 TTS；
  浏览器可通过脱敏工具状态提示用户正在检索。
- 音频帧是实时瞬时数据，不写入日志或持久化。服务端日志只记录受控错误类别和工具名，
  不记录音频、API Key、Function Call 参数或知识库结果。
- 新增模型、音色或音频格式前必须以百炼 Realtime 当前协议为准，并补充前后端协议、
  PCM 边界、打断、资源回收和工具二轮响应测试。
