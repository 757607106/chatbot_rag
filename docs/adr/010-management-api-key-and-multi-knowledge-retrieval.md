# ADR 010：管理 API 密钥、多知识库检索数据面与外部工具治理

## 背景

多知识库控制面（ADR 006）上线后存在三个结构性缺口：

1. 聊天与语音链路固定绑定默认知识库，新建知识库的文档对最终用户不可检索，
   控制面与数据面脱节。
2. 全部管理 API（上传、删除、回滚、切片编辑、召回诊断）无任何身份校验，
   破坏性操作可匿名调用；ADR 005 的"仅限本地或受信网络"约束缺少代码层防线。
3. 外部 MCP 工具调用缺少审计与故障分类：文本聊天把 MCP 服务器故障混入
   `agent_error`，语音链路完全没有 MCP 工具，且模块布局违反
   `tools/` 目录约定（工具装配散落在 `agents/` 中，`knowledge_tools.py`
   名实不符）。

用户确认：MCP Header 中的令牌是临时测试令牌，明文写入运行时 JSON 的现状
（ADR 007）保持不变，不做占位符展开。

## 决策

### 多知识库检索数据面

- `KnowledgeManagementCoordinator.chat_knowledge_bases()` 返回全部已启动
  知识库的句柄，默认知识库排在首位；注册表中未启动的库按需启动。
- 文本 Agent 与实时语音共用 `RAGMiddleware(knowledge_bases=[...])` 原生多库
  能力：模型可通过 `search_knowledge` 的 `knowledge_bases` 参数按库名收窄
  检索范围，未指定时检索全部知识库。
- 新建知识库上传文档后立即可被聊天检索，无需重启或额外配置。

### 管理 API 共享密钥

- 新增可选配置 `CHATBOT_MANAGEMENT_API_KEY`；未配置时管理 API 保持本地
  开发的开放行为，配置后 `/api/v1/knowledge/*` 全部路由要求 `X-Api-Key`
  头与密钥恒时比较（`hmac.compare_digest`）匹配，否则返回 401。
- Next.js BFF 在服务端读取同名环境变量并向 Python 上游附加该头；浏览器
  不持有任何密钥。聊天流、语音 WebSocket 与媒体路由保持公开。
- 这是网络层防护之外的应用层防线，不引入用户体系；多用户身份与权限
  仍留给后续独立设计。

### 外部工具治理

- 语音实时会话的 `Toolkit` 与文本 Agent 一样挂载 `mcps=`，语音系统提示词
  同步补充 MCP 路由与"不得编造业务数据"约束。
- 新增 `McpToolAuditMiddleware`（`on_acting` 钩子）：只对 `mcp__` 前缀的
  工具调用输出结构化审计日志（工具名、最终状态、异常类型、耗时），不记录
  工具参数与返回内容。
- 聊天流协议 v3 新增错误码 `external_tool_error`：异常链归属 `mcp.*`、
  `fastmcp.*` 或 `agentscope.mcp` 模块时，向浏览器明示"外部业务工具故障"，
  与 `agent_error`（模型/服务自身故障）区分，便于差异化重试引导。

### 知识库删除

- 新增 `DELETE /api/v1/knowledge/knowledge-bases/{id}`：仅允许删除已清空
  文档的非默认知识库；删除顺序为"物理 collection → 停止后台服务 →
  删除注册行 → 清理专属目录"，collection 清理失败时知识库仍完好、可直接
  重试，目录清理失败仅残留无链路引用的空目录。

### 模块归位

- MCP 客户端装配移至 `tools/mcp_binding.py`；`agents/knowledge_tools.py`
  更名为 `agents/knowledge_middleware.py`（其实质是 RAGMiddleware 工厂）；
  审计中间件位于 `agents/tool_audit.py`。

## 未采用方案

1. 把全部知识库合并进一个 collection 并用 metadata 过滤：与 ADR 006 的
   独立删除边界决策冲突。
2. 为管理面引入完整登录会话/JWT：当前只有单管理员场景，共享密钥已满足
   "不匿名暴露"的明确需求，属于最小设计。
3. MCP 凭据占位符展开（`${ENV_VAR}`）：用户确认测试令牌短暂有效，
   维持 ADR 007 现状。
4. 有状态 MCP 连接池化：无状态连接是 ADR 007 为按请求创建智能体所做的
   取舍，池化需要独立评估连接生命周期，不在本次范围。

## 影响

- 知识库删除操作不可恢复，前端通过确认对话框与"仅空库可删"约束降低误删。
- 管理密钥一旦配置，直接访问 Python API 的旧脚本必须携带 `X-Api-Key`。
- 审计日志随应用日志滚动，不引入新的持久化存储；需要长期留存时另行
  接入日志收集。
