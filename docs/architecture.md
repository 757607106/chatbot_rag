# 架构说明

## 目标

本项目使用 AgentScope 2.0.5 构建 RAG 聊天机器人，并保持模型、智能体、
文档摄取、知识库和服务入口之间的清晰边界。

## 模块职责

- `config`：从环境变量加载并校验应用配置。
- `models`：使用 AgentScope 官方凭据和模型类创建聊天模型与嵌入模型。
- `rag`：负责文档解析、切块、幂等索引、Qdrant 生命周期和知识库装配。
- `agents`：组合聊天模型、系统提示词和 AgentScope `RAGMiddleware`。
- `services`：向未来的协议适配层提供最终回复和原生事件流聊天用例。

## 依赖方向

`protocol adapter -> services -> agents/rag -> models/config`

下层模块不得依赖具体对外协议。HTTP API、终端界面、向量数据库和文档解析器
应通过边界接口接入，不能把相关逻辑写入智能体主循环。`ChatService` 负责校验
输入并创建 `UserMsg`；协议适配层只负责输入输出转换，不得直接管理模型、
知识库或智能体主循环。具体协议类型不得进入 `services`、`agents` 或 `rag`。

## RAG 数据流

`文件 -> Parser -> ApproxTokenChunker -> DashScopeEmbeddingModel -> QdrantStore -> KnowledgeBase -> RAGMiddleware -> Agent`

索引以相对路径和文件内容摘要生成稳定的文档版本标识。启动时跳过未变化的
文件；内容变化时先写入新版本，再删除同一路径的旧版本，避免正常重试产生
重复索引；文件从受管目录移除后，其旧索引也会被删除。Qdrant 连接应由应用
装配层持有，不能在单次检索中反复打开。

## 当前取舍

当前使用 AgentScope 2.0.5 原生 RAG，而不引入 LlamaIndex。开发环境默认使用
本地持久化 Qdrant，生产环境可通过相同的 `QdrantStore` 切换到远程服务。
智能体先采用 `static` 检索模式，保证每个问题在首次推理前获得知识上下文；
需要让模型自主决定检索时，再作为独立行为变更评估 `agentic` 模式。

当前不绑定具体对外协议或界面框架。新的协议适配层应作为独立架构变更接入，
并复用现有服务接口，不得反向侵入核心模块。
