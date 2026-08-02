# 变更记录

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
