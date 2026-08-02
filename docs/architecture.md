# 架构说明

## 目标

本项目使用 AgentScope 2.0.5 构建 RAG 聊天机器人，并保持模型、智能体、
文档摄取、知识库和服务入口之间的清晰边界。

## 模块职责

- `config`：从环境变量加载并校验应用配置。
- `models`：使用 AgentScope 官方凭据和模型类创建聊天模型与嵌入模型。
- `rag`：负责文档解析、切块、幂等索引、Qdrant 生命周期和知识库装配。
- `agents`：组合聊天模型、系统提示词和 AgentScope `RAGMiddleware`。
- `services`：向协议适配层提供最终回复和原生事件流聊天用例。
- `cli`：使用 prompt_toolkit 读取输入，并用 Rich 渲染 AgentScope 事件。

## 依赖方向

`cli -> services -> agents/rag -> models/config`

下层模块不得依赖具体对外协议。HTTP API、终端界面、向量数据库和文档解析器
应通过边界接口接入，不能把相关逻辑写入智能体主循环。`ChatService` 负责校验
输入并创建 `UserMsg`；协议适配层只负责输入输出转换。CLI 不直接管理模型、
知识库或智能体主循环，终端组件类型也不会进入 `services`、`agents` 或 `rag`。

## CLI 事件流

`prompt_toolkit 输入 -> ChatService.reply_stream -> Agent.reply_stream -> EventRenderer`

终端层直接消费 AgentScope 2.0.5 的事件生命周期。会话期间所有 Rich 输出
都是追加式的：会话控制台在 `patch_stdout` 内创建并写入 `StdoutProxy`，
由 prompt_toolkit 统一安排在输入提示上方打印；不使用 Rich `Live`/`Status`
等原地重绘组件——它们与活动输入提示争夺终端（隐藏光标、覆盖输入区），
是消息回显丢失和光标异常的根源。文本增量按行追加渲染：完整行即时输出，
含 Markdown 语法的行逐行渲染、纯文本逐字打印；代码围栏和连续表格行聚合
成整体渲染；文本块结束时冲刷未换行的剩余内容，不再重排。回复活动状态
（思考、工具执行及已接收字符数）显示在输入提示区，文本开始流式输出时
自动清除。工具调用参数、结果、状态和耗时合并到同一个 `Panel`，JSON 内容
会格式化并高亮；长内容默认截断，可通过 `/verbose` 切换完整输出，开启时
会重放最近一次被截断的工具面板。回复中途失败时，已生成的部分内容先于
错误面板显示。会话期日志经 `RichHandler` 写入同一代理控制台。输入历史由
prompt_toolkit `FileHistory` 持久化，斜杠命令只在 CLI 本地处理。输入读取
任务与回复消费任务通过 `asyncio.Queue` 解耦，模型流式输出期间仍可提交
后续消息，回复消费端会按提交顺序处理。排队消息在提交时即显示用户消息内容，
无需等待前一条回复完成。输入任务在收到独立的 `Esc` 时取消
当前回复任务，但不会销毁会话或已经排队的消息。

CLI 使用非全屏、可滚动的 `user：/ agent：` 消息层级，多行用户消息的续行与
首行内容对齐。输入提示显示回复活动状态和排队数量，不使用固定在窗口底部
的工具栏；每轮完成后显示耗时、模型 token 用量、输出吞吐（tok/s）和工具
调用次数。
终端宽度低于 80 列时，工具面板自动切换为更轻量的边框，避免内容区域过窄。

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

当前终端协议适配采用 prompt_toolkit + Rich，不使用全屏 TUI 或备用屏幕，
以保留终端原生光标、滚动记录和中文输入法行为。输入快捷键、历史、命令补全、
事件分发和富文本输出已有自动化测试；macOS Terminal、iTerm2 及实际部署终端
仍需按 ADR 002 完成手工兼容性验收。
