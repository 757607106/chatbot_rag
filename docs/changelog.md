# 变更记录

## 未发布

- 对齐 assistant-ui `LocalRuntime` 的状态边界：`ChatModelAdapter` 每次提交当前分支的完整
  可见文本历史，后端为每个请求创建独立 AgentScope Agent，通过 `observe` 恢复显式历史，
  移除跨线程共享工作记忆的全局 Agent 和串行锁。
- 使用 AgentScope 2.0.5 官方 `agentic` RAG，由模型结合当前问题和显式历史自主判断是否
  调用 `search_knowledge`，并在存在指代时生成自包含查询。
- agentic 检索必须先完成工具调用再输出唯一最终答案，不向用户展示检索判断、调用计划
  或中间的证据不足结论。
- 收紧事实型生成约束：只输出回答当前问题所需的最小内容，并逐句删除检索证据不支持的
  界面名称、路径、数字、示例、建议和限制条件。
- 图片继续按回答中明确放置且属于本轮检索的内部标记原位转换为 assistant-ui image part；
  不按关键词猜测图片位置，不自动追加模型未引用的检索图片。
- 在现有聊天历史侧栏增加“知识库”固定入口，保持聊天主体、Composer、线程列表和折叠布局
  不变，并同步支持移动端抽屉。
- 将知识库后台升级为多知识库控制面，支持知识库创建与切换，并为每个
  知识库分配独立文件目录、Qdrant collection、后台队列和检索诊断边界。
- 新增单个文本切片手工编辑：以正文 SHA-256 做乐观并发检查，原子更新 Qdrant payload 与
  新向量，并记录不含正文的编辑审计。
- 新增原文件版本历史与异步版本回滚；回滚会重新解析历史文件并替换活动索引，失败时保留
  之前的活动版本。
- SQLite 自动把旧版全局文件名唯一约束迁移为 `knowledge_base_id + source_path` 复合约束，
  既有默认知识库、文档目录和 collection 保持兼容。
- 新增无需登录的知识库管理 API 和 Next.js 同源 BFF，供本地或受信网络直接使用。
- 受管目录中的旧式 `.doc`、`.ppt` 会显示为不支持状态，不再静默忽略。
- 为未来权限角色、聊天附件、对象存储、网页同步、离线评测和 Agent 链路追踪保留稳定边界。
- 图片允许列表由 `search_knowledge` 的内部工具结果建立，工具参数、检索原文和内部媒体
  标记不向浏览器公开。
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
