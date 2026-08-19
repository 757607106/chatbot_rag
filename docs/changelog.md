# 变更记录

## 未发布

- 聊天与实时语音共用对话行为策略：区分用户意图不明确、私有事实不确定和
  工具证据不足三类情况；用户要求跳过查询不能绕过必需验证，澄清候选项、
  原因和建议同样受证据约束，避免编造客户端、版本、功能或失败原因。
- 新增显式启用的真实模型提示词回归，覆盖单问句澄清、禁用话术、知识库路由
  抗绕过和空证据拒绝猜测；默认测试不访问外部模型。
- 系统提示词身份升级为“面向销售与录单场景的 AI 数字员工”：声明商品目录
  检索、客户/仓库/经手人查询、销售单开立（草稿/预收/正式）、单据查询、
  修改与作废，以及手写/打印下单图片识别（划删、涂改、中文数字与算式规则）
  的文字与图片双开单方式；配套 emoji 禁令具体化（点名常用 emoji、
  波浪号与符号列表项）。
- 拟人化回复改为最小充分澄清和分级情绪响应：普通歧义每轮只问一个主要问题，
  工具缺少多个必填字段时才集中询问；自然停顿使用短句和分段，不再用固定语气词
  表演思考；工具调用前不输出过渡话术，并禁止无依据的结果承诺。
- 新增 debug 开关 `CHATBOT_DEBUG`（默认 `false`）：开启后 `chatbot_rag` 各模块
  输出 DEBUG 级日志（检索、流式处理等），排障时在 `.env` 中临时打开。
- 工具路由提示词改为按问题意图判定：说明类问题（是什么/为什么/怎么做）走知识库，
  实时数据类问题（多少/当前/我的/最近的）走 MCP，混合意图同时调用两类工具；
  兑底规则从单向“优先知识库”改为按意图双向兑底，并增加仅用于路由判断的对比示例，
  解决实时业务问题被知识库抑制的问题。
- `agents/rag_agent.py` 更名为 `agents/chat_agent.py`，装配函数更名为
  `create_chat_agent`，默认智能体名从 `rag_assistant` 改为 `assistant`：
  该智能体同时承担多知识库检索、MCP 外部业务工具和对话编排，名称不再局限于 RAG。

- 聊天与实时语音链路接入多知识库检索数据面：`chat_knowledge_bases()` 把全部已启动
  知识库交给 `RAGMiddleware`，模型可用 `knowledge_bases` 参数按库名收窄范围，
  新建知识库上传文档后立即可被检索；默认知识库仍排在首位。详见
  `docs/adr/010-management-api-key-and-multi-knowledge-retrieval.md`。
- 新增可选管理密钥 `CHATBOT_MANAGEMENT_API_KEY`：配置后 `/api/v1/knowledge/*`
  全部路由要求 `X-Api-Key` 头恒时比较匹配；Next.js BFF 在服务端附加该头，
  浏览器不持有密钥；未配置时保持本地开发开放行为。
- 新增 `DELETE /api/v1/knowledge/knowledge-bases/{id}` 与前端删除入口：仅允许删除
  已清空文档的非默认知识库，删除时同步移除独立目录、版本目录和 Qdrant collection。
- 实时语音会话与文本 Agent 同箱绑定 MCP 外部工具，语音系统提示词补充外部业务
  数据路由与“不得编造业务数据”约束。
- 聊天流协议 v3 新增错误码 `external_tool_error`：MCP 客户端栈故障与模型自身
  故障分离，便于前端差异化重试引导。
- 文本 Agent 新增 `McpToolAuditMiddleware`：对 `mcp__` 工具调用输出结构化审计
  日志（工具名、状态、异常类型、耗时），不记录工具参数与返回内容。
- 模块归位：MCP 客户端装配移至 `tools/mcp_binding.py`，`agents/knowledge_tools.py`
  更名为 `agents/knowledge_middleware.py`，新增 `agents/tool_audit.py`。

- Web NDJSON 协议升级到版本 3，为文本聊天增加脱敏的 MCP 工具状态；前端使用
  assistant-ui 原生 `tool-call` part 显示受控中文业务标签，不公开服务器名、真实工具名、
  参数、原始结果或异常详情。
- Voice Mode 改为单个百炼 `qwen-audio-3.0-realtime-flash` 双工 WebSocket 会话：
  浏览器以 20ms PCM16 帧持续上行，服务端同步返回转写和音频增量，前端收到即播放，
  并使用 `smart_turn` 支持语义分轮和播报打断。
- 实时语音模型通过 Function Calling 使用 AgentScope 2.0.5 `Toolkit` 中同一个只读
  `search_knowledge`；工具执行留在服务端，只向浏览器公开脱敏的开始/完成状态。
- 新增 `WS /api/v1/voice/realtime` 受控协议、PCM 帧校验和 Origin 允许列表；百炼 Key
  只用于 Python 服务到上游的握手，浏览器使用显式公共 WebSocket 地址。
- 删除旧的完整录音 ASR、文本 Agent、完整 WAV TTS 串行链路，以及对应的输入框听写、
  消息朗读、HTTP/BFF API、配置、测试和无职责代码；文本聊天链路保持不变。
- Voice Mode 保留按会话状态和实时音量驱动的 Canvas 液态气泡、静音/结束控制、降低动效
  与屏幕阅读器状态。
- 修复结束 Voice Mode 后文字记录消失：按轮次收集最终用户/助手转写及断开前已生成的助手
  文字，结束时清除 assistant-ui 临时 voice messages，并原子写入当前 `LocalRuntime`
  基础分支；不会重复调用文本模型，后续文本提问可继续使用这段语音上下文。
- 智能体新增 MCP 外部工具能力：`CHATBOT_MCP_SERVERS_JSON` 以标准 `mcpServers`
  JSON 声明 SSE/HTTP 服务器并直接提供完整鉴权 Header；`enableTools`
  可限制模型可见工具，当前示例默认排除下单、作废、更新和同步类变更操作；
  远程工具与 `search_knowledge` 同箱注册，外部业务数据查询与知识检索共用同一
  智能体，工具调用过程不进入公共协议。
- 完善文本智能体的工具路由提示：混合问题可同时调用知识库与 MCP，并按工具 schema
  生成参数；工具结果只作为数据证据处理，单类工具失败不阻断已有充分证据的其他部分。
- 远程 Markdown 图片同时支持 HTTP 和 HTTPS 地址，不再仅限 HTTPS；允许主机配置和
  默认端口约束保持不变（HTTP 默认 80、HTTPS 默认 443）。
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
