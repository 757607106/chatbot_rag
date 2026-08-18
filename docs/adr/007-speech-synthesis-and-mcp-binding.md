# ADR 007：服务端语音合成与 MCP 工具绑定

> 状态：已接受。

## 背景

聊天界面需要把助手回答朗读出来，且智能体除知识库检索外还要访问云打印计费等外部
业务系统。浏览器自带的 Web Speech 合成音色与发音不受项目控制；外部业务数据只能
通过带鉴权的 SSE MCP 服务器（如 `yunprint-billing`）获取。百炼模型密钥必须来自
系统环境变量，MCP Header 则作为完整值写入运行时 `mcpServers` JSON。

## 备选方案

1. 前端直接调用浏览器 `speechSynthesis`，外部系统用自写 HTTP 工具访问。
2. 后端直接依赖 dashscope SDK 写 TTS 服务和 MCP 客户端。
3. 复用 AgentScope 2.0.5 原生能力：`DashScopeCosyVoiceTTSModel` 对接百炼
   Qwen-Audio-TTS WebSocket 合成入口，`MCPClient` + `Toolkit(mcps=...)` 装配
   远程 MCP 工具。

方案一音色与可用性依赖浏览器，且鉴权令牌会暴露到浏览器。方案二重复封装官方已经
提供的模型与客户端抽象，违背项目“优先复用 AgentScope 原生能力”的基线。

## 决策

采用方案三：

- **语音合成**：`models/tts_factory.py` 用 AgentScope
  `DashScopeCosyVoiceTTSModel`（`dashscope.audio.tts_v2` WebSocket 入口，
  Qwen-Audio-TTS 与 CosyVoice 共用该入口）创建非流式模型，默认
  `CHATBOT_TTS_MODEL=qwen-audio-3.0-tts-plus`、`CHATBOT_TTS_VOICE=longanlingxin`
  （plus 专属旗舰音色）。`SpeechSynthesisService` 解码完整 WAV；
  `POST /api/v1/speech/tts` 返回 `audio/wav`；前端助手消息操作栏的朗读按钮
  调用同源 Next.js BFF 播放，替换原浏览器本地合成。
- **MCP 绑定**：`CHATBOT_MCP_SERVERS_JSON` 保存标准 `mcpServers` JSON，
  `headers.Authorization` 直接包含最终 Bearer 值，不做占位符展开；仅接受 `sse`
  与 `http` 类型。`agents/mcp_binding.py` 把定义转换为 AgentScope
  `MCPClient`（`HttpMCPConfig`，URL 以 `/sse` 结尾自动走 SSE 传输并携带自定义
  header），并使用**无状态连接**：每次工具调用临时建会话，避免在按请求创建
  智能体的架构中泄漏长连接。`Toolkit(mcps=...)` 与 `search_knowledge` 同箱注册，
  模型按系统提示词区分知识检索与外部业务数据查询。可选 `enableTools`
  会转换为 AgentScope 工具允许列表；针对当前服务器，示例默认排除会改变业务状态的工具。
- **密钥**：模型密钥统一使用 `DASHSCOPE_API_KEY`；MCP 令牌直接位于运行时 JSON Header；
  合成 WebSocket 端点可用 dashscope 原生 `DASHSCOPE_WEBSOCKET_BASE_URL` 覆盖。
  浏览器不持有任何密钥，朗读请求全部经同源 BFF 代理。

## 后续演进约束

- TTS 单次文本上限 20,000 字符，对齐百炼当前非流式 SDK 限制；
  超长文本分段与边合成边播放需独立验收。
- 语音识别输入和 Voice Mode 保持独立的录音生命周期，并复用本 ADR 的合成服务；
  具体决策见 `008-server-asr-and-agent-voice-mode.md`。
- 变更类 MCP 工具在引入人工确认、权限校验和审计前不得加入默认
  `enableTools` 允许列表。
- MCP 工具结果默认不进入公共 NDJSON；需要向用户展示工具进度时必须先经过
  脱敏与允许列表设计。
