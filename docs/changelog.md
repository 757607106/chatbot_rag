# 变更记录

## 未发布

- 使用 Rich + prompt_toolkit 重新实现交互式 CLI，并恢复 `chatbot-rag` 命令。
- 增加 AgentScope 原生事件流渲染、思考状态、Markdown 回复及工具调用/结果面板。
- 增加多行输入、持久化历史、方向键回看、斜杠命令补全和本地帮助命令。
- 增加 CLI 输入、补全、事件渲染、会话循环和流式服务测试。
- 优化为紧凑的 `user：/ agent：` 对话布局，增加动态队列状态和回复运行指标。
- 合并工具调用与结果面板，增加执行耗时、窄终端布局、长内容截断及
  `/verbose` 完整输出模式。
- 修复回复期间提交的排队消息不显示内容的问题：用户消息在提交时即显示，
  不再等到回复完成后才出现。
- 配置日志经由 Rich `RichHandler` 输出到同一控制台，避免 AgentScope 中间件
  错误日志打断终端渲染。

## 0.1.0

- 初始化标准 `src layout` 工程结构。
- 固定 AgentScope 2.0.5 运行时依赖。
- 增加 DashScope 模型、RAG 智能体和聊天服务。
- 将 DashScope 聊天模型的 `temperature` 设为 `0.7`、`top_p` 设为 `0.8`。
- 增加 DashScope 嵌入模型、Qdrant 持久化和 `KnowledgeBase`。
- 增加 Markdown、PDF、Word 文档的幂等解析、切块与索引流程。
- 默认使用 `tests/docs_test` 测试资料，并输出解析与索引阶段进度。
- 使用 AgentScope `RAGMiddleware` 静态检索模式替换自定义检索工具。
- 增加单元测试、集成契约测试和质量检查配置。
- 移除未通过真实终端兼容性验收的 Textual CLI、命令入口及专属流式适配，
  保留 AgentScope、RAG 和聊天服务核心，等待独立评估新的交互技术路线。
