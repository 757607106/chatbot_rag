# 架构说明

## 目标

本项目使用 AgentScope 2.0.5 构建 RAG 聊天机器人，并使用
assistant-ui 构建 Web 对话界面。架构必须保持界面、对话协议、应用服务、
智能体、文档摄取、知识库和模型之间的清晰边界。

## 模块职责

- `config`：从环境变量加载并校验应用配置。
- `models`：使用 AgentScope 官方凭据和模型类创建聊天模型与嵌入模型。
- `rag`：负责文档解析、切块、幂等索引、Qdrant 生命周期和知识库装配。
- `agents`：组合聊天模型、系统提示词和 AgentScope `RAGMiddleware`。
- `services`：向协议适配层提供最终回复和原生事件流聊天用例。
- `services/api`：FastAPI 协议边界，负责请求校验、事件转换、资源装配和错误映射。
- `frontend`：独立 Next.js 工程，使用 assistant-ui 组件和 Runtime 渲染对话交互。

## 依赖方向

`browser UI -> assistant-ui LocalRuntime -> ChatModelAdapter -> HTTP adapter -> services -> agents/rag -> models/config`

下层模块不得依赖具体对外协议。HTTP API、终端界面、向量数据库和文档解析器
应通过边界接口接入，不能把相关逻辑写入智能体主循环。`ChatService` 负责校验
输入并创建 `UserMsg`；协议适配层只负责输入输出转换，不得直接管理模型、
知识库或智能体主循环。具体协议类型不得进入 `services`、`agents` 或 `rag`。
前端组件不直接请求模型、解析后端原生事件或持有任何服务端密钥。

## 目标 Web 对话链路

```text
页面/业务组件
  -> assistant-ui primitives 和 LocalRuntime
  -> 项目 ChatModelAdapter
  -> 同源 BFF（仅在鉴权或部署需要时）
  -> Python HTTP 协议适配层
  -> ChatService.reply_stream
  -> AgentScope Agent/RAG
```

assistant-ui 的 UI 层只通过 Runtime 读写对话状态。首个 Web 版本选择
`LocalRuntime` 与自有 `ChatModelAdapter`，让 assistant-ui 管理页面内消息、编辑、
重试、分支和取消；Python 后端仍是模型、RAG、工具权限和持久化数据的
真实源。暂不引入 Assistant Cloud、Vercel AI SDK 或第二套智能体编排框架。

HTTP 层必须把 AgentScope 原生事件转换为独立、版本化的 Web 流式协议；
浏览器不感知 Python 类或 AgentScope `AgentEvent` 结构。协议至少表达回复开始、
文本增量、经脱敏的工具状态、完成与错误，并让用户取消信号贯穿整条链路。
内部思维链不进入公共协议，需要表达进度时只发送明确标记为可公开的阶段状态。

## 前端内部边界

- `app`：路由、layout、客户端边界和应用装配。
- `components/assistant-ui`：registry 拉取并受版本控制的 assistant-ui 组件源码。
- `components/ui`：不含聊天业务语义的 shadcn 视觉原语。
- `features/chat/runtime`：唯一 assistant-ui Runtime 适配和消息映射边界。
- `features/chat/api`：HTTP 请求、流解析、取消和错误分类。
- `features/chat/schemas`：与后端协议对齐的前端边界类型。

registry 组件是可定制源码，但通用组件不得直接 `fetch`，业务组件不得
自建一套与 assistant-ui 平行的对话状态。设计 token、响应式布局、键盘可用性、
可见焦点、降低动效和不可信 Markdown/链接渲染是前端验收条件。

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

当前已实现单会话纯文本流式竖切片：FastAPI 把 AgentScope 事件转换为版本 1
NDJSON，Next.js BFF 负责同源转发，项目 `ChatModelAdapter` 校验并累积增量，
assistant-ui `LocalRuntime` 管理浏览器内消息状态。页面组件直接同步自 assistant-ui
官方 ChatGPT demo，不在 registry 组件中加入项目自定义视觉层。

锁定的 `@assistant-ui/react@0.15.1` 在 Next.js 开发模式的 React Strict Mode
双重挂载下会让初始 LocalRuntime 线程失去绑定，表现为空态标题缺失、Composer
受控值回滚；生产构建不受影响。`next.config.ts` 暂时显式关闭 Strict Mode，且已分别
用开发服务器和生产构建验证。升级 assistant-ui 时必须重新验证并优先恢复 Strict Mode。

后端当前复用单个有状态智能体并串行处理请求，只能作为单进程单会话基线。
附件、工具事件、语音、服务端线程隔离和持久化仍需独立设计与验收。详见
`docs/adr/003-assistant-ui-web-frontend.md`。
