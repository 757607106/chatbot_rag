# 变更记录

## 未发布

- 将 AgentScope `RAGMiddleware` 从 `static` 切换为 `agentic`，注册官方
  `search_knowledge` 工具，由模型判断是否需要项目知识并改写自包含查询；通用任务不再
  固定执行检索。协议层从内部工具结果建立图片允许列表，但不向浏览器公开工具参数或原文。
- 扩展默认文档摄取范围，新增 `.markdown`、`.txt`、`.pptx`、`.xls` 和 `.xlsx`；
  PPTX 文本块保留幻灯片序号，Excel 按工作表拆分并保留工作表名。PPTX 和 Excel
  暂只索引文本与表格，不抽取图片进入文本 Embedding 链路。
- 系统性修复检索范围丢失和冲突内容混答：Markdown 按标题建立自然章节，所有格式的
  Chunk 保留文档来源，PDF 同时保留页码；查询移除说话人标签后召回 50 个候选，再由
  qwen3-rerank 按全部显式条件精排为最终 Top 5，且不补回未经精排的候选。
- 将事实型 RAG 回答的聊天模型 `temperature` 从 `0.7` 降至 `0.1`，减少同一证据下的
  随机发挥；Prompt 改为与具体产品无关的证据匹配契约。
- qwen3-rerank 网络调用使用 15 秒超时和最多两次尝试，减少瞬时 TLS/握手故障触发
  向量排序回退的概率。
- 增加 Markdown 外链、Word 内嵌和 PDF 页内图片摄取，使用文档清单管理本地图片及
  允许主机上的远程图片缓存，并在源文档删除后清理无引用资产。
- 将 Web NDJSON 协议升级到版本 2，增加受控 `image_part`，通过 Next.js 媒体 BFF
  映射为 assistant-ui 原生 `ImageMessagePart`，支持加载失败和全屏预览。
- 图片标记改为在对应说明位置转换成 `image_part`，支持文本、图片交错渲染；未被回答
  引用的检索图片不再统一追加到消息末尾，并过滤非本轮、重复和超量标记。
- 保持文本 embedding，通过检索文本中的内部媒体引用返回相关图片；摄取管线版本变化
  或媒体清单缺失时自动重建旧索引。
- 废弃并移除交互式命令行层、可执行入口、专属测试和直接依赖，保留 RAG、
  智能体及协议无关的聊天服务。
- 优化 RAG 智能体系统提示词为中文，明确引用来源格式和回答语言要求。
- 确立 Next.js、TypeScript 与 assistant-ui `LocalRuntime` 的 Web 前端架构，补充
  前后端协议边界、流式聊天、依赖锁定、前端测试、安全与体验规范。
- 增加 FastAPI `POST /api/v1/chat/stream`，将 AgentScope 回复事件转换为版本化
  NDJSON，并过滤思考过程与内部异常细节。
- 增加 Next.js 同源 BFF、NDJSON 解析器和 assistant-ui `ChatModelAdapter`，支持
  累积文本流、取消与公开错误。
- 直接接入 assistant-ui 官方 ChatGPT demo 页面源码及配套会话栏组件，不维护
  另一套自定义聊天视觉实现。
- 记录并隔离 assistant-ui 0.15.1 在 Next.js 开发 Strict Mode 双重挂载下的
  LocalRuntime 初始线程绑定问题；暂时关闭 Strict Mode，升级时必须重新验证。

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
