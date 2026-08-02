# ADR 001：采用 AgentScope 原生 RAG

## 状态

已采纳。

## 背景

项目以 AgentScope 2.0.5 为固定技术基线，需要完成文档解析、切块、向量化、
持久化检索以及与智能体推理循环的集成。备选方案包括引入 LlamaIndex，或使用
AgentScope 原生 RAG 模块。

## 决策

使用 AgentScope 2.0.5 的 `DashScopeEmbeddingModel`、`QdrantStore`、
`KnowledgeBase` 和 `RAGMiddleware` 构建完整链路。开发环境使用本地 Qdrant
持久化目录，生产环境通过配置切换远程 Qdrant。首个版本采用 `static` 中间件
模式，确保每轮问答执行检索。

## 备选方案

LlamaIndex 提供更丰富的数据连接器、摄取转换和高级检索器，但会在现有项目中
引入第二套文档、索引、模型和查询抽象。当前需求不需要这些额外能力，因此暂不
引入；未来只有在明确需要其高级检索能力时，才通过 `rag` 模块边界进行评估。

## 影响

- Agent、模型、消息和 RAG 生命周期保持在同一 AgentScope 版本契约内。
- 减少适配代码和直接依赖，便于测试及后续升级。
- 当前切块和检索策略以 AgentScope 2.0.5 能力为限，高级混合检索需要另行设计。
