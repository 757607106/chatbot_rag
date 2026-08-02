# 架构说明

## 目标

本项目使用 AgentScope 2.0.5 构建 RAG 聊天机器人，并使用
assistant-ui 构建 Web 对话界面。架构必须保持界面、对话协议、应用服务、
智能体、文档摄取、知识库和模型之间的清晰边界。

## 模块职责

- `config`：从环境变量加载并校验应用配置。
- `models`：创建聊天、嵌入模型，并通过 DashScope SDK 适配 qwen3-rerank。
- `rag`：负责文档与图片解析、媒体资产、切块、幂等索引、Qdrant 生命周期和知识库装配。
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

```text
索引：文件 -> Parser -> ContextPreservingChunker(ApproxTokenChunker)
    -> DashScopeEmbeddingModel -> QdrantStore

查询：Agent 判断问题是否需要项目知识 -> search_knowledge
    -> 清理查询前缀 -> Qdrant 向量候选 Top 50 -> qwen3-rerank -> 最终 Top 5
    -> 工具结果 -> Agent

通用任务：Agent 判断与知识库无关 -> 不调用 search_knowledge -> 直接生成
```

Markdown 解析器以标题作为 `Section` 自然边界，图片只转换为原位内部引用，不再创建
人为章节边界。解析器把完整标题路径写入章节元数据，`ContextPreservingChunker` 在
`ApproxTokenChunker` 执行长度切分前后为每个文本块补充文档来源和该路径；Word 文本
和 TXT 至少保留来源，PDF 文本同时保留来源与页码，PPTX 保留幻灯片序号，Excel 按
工作表建立自然边界并保留工作表名。因此所有格式的 Chunk 脱离前后文后仍有稳定范围，
不依赖生成模型猜测它属于哪个文档、章节、幻灯片或工作表。PPTX 和 Excel 当前使用
AgentScope 原生 Parser 读取文本与表格，并显式关闭图片抽取，避免文本 Embedding
接收未经过媒体资产边界处理的多模态块。

索引以相对路径和文件内容摘要生成稳定的文档版本标识。启动时跳过未变化的
文件；内容变化时先写入新版本，再删除同一路径的旧版本，避免正常重试产生
重复索引；文件从受管目录移除后，其旧索引也会被删除。Qdrant 连接应由应用
装配层持有，不能在单次检索中反复打开。

`RerankingKnowledgeBase` 继承 AgentScope 原生 `KnowledgeBase`，只扩展 `search`：
原生向量检索负责高召回，qwen3-rerank 使用问答相关性和完整显式条件匹配指令负责高精度。
向量检索与重排序共用去除 AgentScope 说话人标签后的纯问题，重排序候选显式携带真实来源，
内部媒体标记不会发送给模型。重排序成功后只返回模型确认的结果并采用其相关性分数，不为
凑满 Top K 补回未经精排的候选。瞬时网络异常会执行一次有界重试，最终失败时记录内部
错误并回退到向量 Top K；向量检索无结果时，系统提示要求明确拒答且不得伪造来源。

生成阶段使用低随机性的事实问答参数，并以通用证据契约核对问题中的对象、属性、版本、
环境、时间与适用条件。实现中不包含某个具体产品或问题的关键词分支。

## 当前取舍

当前使用 AgentScope 2.0.5 原生 RAG，而不引入 LlamaIndex。开发环境默认使用
本地持久化 Qdrant，生产环境可通过相同的 `QdrantStore` 切换到远程服务。
智能体采用 `agentic` 检索模式，将 `RAGMiddleware.list_tools()` 返回的官方
`search_knowledge` 注册到 `Toolkit`。涉及项目资料、产品功能、操作步骤和私有事实的
问题必须先检索；明确无关的通用问答、写作、翻译和创意任务不检索。指代型问题由模型
结合对话历史改写为自包含查询，结果不足时可换一种明确表达再次检索。该模式减少无关
问题的 Embedding、Qdrant 和重排序开销，但是否检索依赖模型遵循工具使用契约，因此
需要用知识库问题与无关问题两类用例持续评估工具调用决策。

当前已实现单会话文本与文档图片流式竖切片：FastAPI 把 AgentScope 事件转换为版本 2
NDJSON，Next.js BFF 负责同源转发，项目 `ChatModelAdapter` 校验并累积文本及
`ImageMessagePart`，assistant-ui `LocalRuntime` 管理浏览器内消息状态。页面主体继续
同步自 assistant-ui 官方 ChatGPT demo；图片 part 使用可审查的项目组件提供加载、
失败、键盘焦点和全屏预览状态。

锁定的 `@assistant-ui/react@0.15.1` 在 Next.js 开发模式的 React Strict Mode
双重挂载下会让初始 LocalRuntime 线程失去绑定，表现为空态标题缺失、Composer
受控值回滚；生产构建不受影响。`next.config.ts` 暂时显式关闭 Strict Mode，且已分别
用开发服务器和生产构建验证。升级 assistant-ui 时必须重新验证并优先恢复 Strict Mode。

后端当前复用单个有状态智能体并串行处理请求，只能作为单进程单会话基线。
用户上传附件、工具事件、语音、服务端线程隔离和持久化仍需独立设计与验收。详见
`docs/adr/003-assistant-ui-web-frontend.md`。

## 文档图片数据流

`Markdown/Word/PDF -> 媒体感知 Parser -> MediaAssetStore + 文本媒体标记 -> 文本 Embedding -> Qdrant -> search_knowledge 工具结果 -> Agent 原位引用 -> Web image_part -> ImageMessagePart`

图片二进制不进入文本 embedding 或 NDJSON。内嵌图片持久化到配置的媒体目录；远程
图片只登记允许主机上的 HTTPS 地址并按需缓存。每个源文档维护图片清单，文档删除或
图片减少后清理无引用资产。内部 `<chatbot-media>` 标记只用于把检索命中的文本块与
图片资产关联。模型仅在采用相邻证据时把原标记放到对应说明之后；协议层跨文本增量
解析标记，并从 `search_knowledge` 的内部工具结果事件建立本轮允许列表。只有标记属于
本轮检索结果时才原位转换为受控同源 URL，并对重复、编造和超量标记执行过滤；工具
参数、检索原文和内部标记不会进入浏览器，未被回答引用的图片也不会在末尾追加。

图片检索采用“文本召回、相邻图片随块返回”，保持现有 `text-embedding-v4`、
`qwen3-rerank` 和 Qdrant collection，不为图片单独生成向量。需要按视觉内容搜索图片时，
必须作为独立架构变更评估多模态 embedding、重建索引和模型输入能力。详见
`docs/adr/004-rag-document-images.md`。
