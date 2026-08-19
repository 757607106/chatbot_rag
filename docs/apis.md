# API 说明

## Web 流式聊天

### `POST /api/v1/chat/stream`

请求体：

```json
{
  "messages": [
    {"role":"user","content":"上一问"},
    {"role":"assistant","content":"上一答"},
    {"role":"user","content":"当前问题"}
  ]
}
```

`messages` 是 assistant-ui 当前分支的完整可见文本历史，必须以用户消息开始和结束，
且 `user`、`assistant` 角色严格交替。每条 `content` 会去除首尾空白，不能为空，最大
长度为 20,000 个字符；最多 100 条消息，总字符数最多 100,000，额外字段会被拒绝。
响应媒体类型为 `application/x-ndjson`，每行是一个独立 JSON 事件。公共协议版本固定为
`3`，正常事件顺序如下：

```json
{"version":3,"type":"message_start","message_id":"reply-id"}
{"version":3,"type":"tool_status","message_id":"reply-id","tool_call_id":"mcp-1","operation":"list_sales_orders","status":"running"}
{"version":3,"type":"tool_status","message_id":"reply-id","tool_call_id":"mcp-1","operation":"list_sales_orders","status":"completed"}
{"version":3,"type":"text_delta","message_id":"reply-id","text":"文本增量"}
{"version":3,"type":"image_part","message_id":"reply-id","url":"/api/media/64位资产标识","filename":"操作步骤.png"}
{"version":3,"type":"message_end","message_id":"reply-id","finish_reason":"completed"}
```

`tool_status` 只在文本 Agent 执行 MCP 工具时出现。`tool_call_id` 是当前回复内按顺序
生成的公共标识，不复用模型或 MCP 的内部调用标识；`operation` 只能取前端允许列表中的
受控业务操作，`status` 为 `running`、`completed` 或 `failed`。协议不发送 MCP
服务器名、真实工具名、参数、原始结果或异常详情；未知 MCP 工具统一映射为
`external_business`。

`image_part` 只在本次 RAG 检索命中了关联图片，且模型在对应说明位置引用该图片时出现；
事件会紧跟对应的文本段落或列表项，每次回复最多发送 3 张，不会在结束事件前统一追加。
每张图片前必须有自上一张图片后新增的非空正文，连续图片标记只转换第一张。
`url` 必须是同源 `/api/media/<asset_id>`，不会向浏览器公开文档磁盘路径或远程
原始图片地址。前端必须将文字和图片累积为完整 assistant-ui 消息 parts；后续事件
不得覆盖此前图片。

HTTP 响应头发出后的失败通过流内错误表达：

```json
{"version":3,"type":"error","code":"agent_error","message":"可公开错误文案"}
```

错误码为 `agent_error`、`external_tool_error`、`incomplete_stream` 或 `protocol_error`；
`external_tool_error` 表示 MCP 外部业务工具栈故障（如服务器不可达、超时），与模型或
助手服务自身故障（`agent_error`）区分，可直接重试。公共协议发送助手
回复生命周期、MCP 脱敏状态、文本增量和已脱敏的文档图片引用；AgentScope 思考、
工具参数、工具原始结果、检索内部标记和异常细节不会进入浏览器。模型输出的图片标记
只有属于本轮检索结果时才会转换为图片事件，编造、跨轮复用、重复或超过数量上限的
标记会被丢弃。前端必须按 `message_id` 校验事件归属。

## 文档图片

### `GET /api/v1/media/{asset_id}`

返回摄取阶段登记的浏览器安全图片。内嵌图片直接从本地媒体仓库读取；远程 Markdown
图片首次访问时由后端从 `CHATBOT_REMOTE_IMAGE_HOSTS` 允许的 HTTP/HTTPS 主机下载，并在
校验响应状态、MIME、文件签名和 10 MB 上限后缓存。响应使用
`Content-Disposition: inline`、`X-Content-Type-Options: nosniff` 和私有缓存头。

浏览器不直接调用该地址，而是请求 Next.js 同源 `GET /api/media/{asset_id}` BFF。
未知标识返回 404；远程图片暂时无法取得返回 502。

每个请求创建独立 AgentScope 智能体，并把 `messages` 中除最后一条外的历史通过
`Agent.observe` 写入本次上下文，再以最后一条用户消息触发 `reply_stream`。请求之间不
共享工作记忆，也不需要用全局锁串行化。当前协议不提供服务端会话持久化；刷新后历史、
多端同步和可恢复流需要单独的服务端状态方案。

## 应用服务

非 HTTP 调用可直接使用：

```python
async def create_agent():
    return await create_chat_agent(settings, knowledge_bases)

service = ChatService(create_agent)
conversation = [ConversationTurn(role="user", content="用户问题")]

reply = await service.reply(conversation)

async for event in service.reply_stream(conversation):
    ...
```

`reply_stream` 返回 AgentScope 2.0.5 原生 `AgentEvent`，只允许协议适配层消费。
智能体使用 AgentScope 官方 `agentic` RAG：模型结合当前问题和显式对话历史判断是否调用
只读 `search_knowledge`。知识库工具调用、所有工具参数和原始结果不会进入公共 NDJSON；
MCP 只公开受控业务操作及运行、完成或失败状态。若知识库工具结果含有关联图片，协议层
只在内部提取媒体允许列表。

## RAG 摄取

```python
async with open_knowledge_base(settings) as knowledge_base:
    summary = await DocumentIngestor(
        knowledge_base,
        ContextPreservingChunker(
            ApproxTokenChunker(chunk_size=512, overlap=64),
        ),
    ).ingest_directory(settings.documents_path)
```

`IngestionSummary` 分别返回本次建立索引、因内容未变化而跳过，以及从受管目录
移除后同步删除的文档数量。当前支持 `.md`、`.markdown`、`.txt`、`.pdf`、
`.docx`、`.pptx`、`.xls` 和 `.xlsx` 文件；旧式 `.doc` 和 `.ppt` 不支持。Markdown
外链图片、Word 内嵌图片及 PDF 页内图片会转换为内部媒体引用并绑定到相邻文本块；
PPTX 和 Excel 当前只解析文本与表格，不抽取图片。向量仍由文本生成。摄取管线版本
变化或媒体清单缺失时会自动重建对应文档索引。

## RAG 检索与重排序

运行时使用 `CHATBOT_RERANK_CANDIDATE_TOP_K` 控制向量候选数量，默认 `50`；
`CHATBOT_RAG_TOP_K` 控制每次工具检索重排序后返回给模型的数量，默认 `5`。候选数量不得小于
最终数量，且不得超过 qwen3-rerank 单次支持的 `500` 个文档。重排序模型默认由
`CHATBOT_RERANK_MODEL=qwen3-rerank` 指定，与聊天和嵌入模型共用
`DASHSCOPE_API_KEY`。

向量检索前会移除 AgentScope 自动添加的说话人标签，但保留问题本身的业务前缀。
重排序采用问答检索指令，要求候选直接回答问题，并逐项匹配所有明确对象与适用条件。
候选会携带真实文档来源；成功精排后只返回模型确认的结果，并把公开的相关性分数写回
搜索结果，不补入未经精排的内容。网络异常会在每次 15 秒超时限制下执行最多两次尝试；
最终失败时回退到原始向量 Top K，并在服务端记录错误。系统不会把上游响应细节或内部
`<chatbot-media>` 标记发送给浏览器。

## 实时语音

### `WS /api/v1/voice/realtime`

该地址为浏览器到项目后端的受控 WebSocket，不是百炼协议透传。握手必须携带在
`CHATBOT_REALTIME_VOICE_ALLOWED_ORIGINS` 中声明的 HTTP/HTTPS `Origin`；缺失或不匹配
时以关闭码 `1008` 拒绝。服务未装配时使用 `1011`。浏览器通过
`NEXT_PUBLIC_CHATBOT_VOICE_WS_URL` 指向该地址，生产环境必须使用 `wss`。
Origin 允许列表只限制浏览器来源，不构成用户身份认证；当前接口只适用于本地或受信网络，
公网部署必须在反向代理或 API 网关增加身份认证、连接数限制和调用频率限制。

服务接受连接后，以服务端 `DASHSCOPE_API_KEY` 建立独立百炼会话。默认配置为：

- 模型 `CHATBOT_REALTIME_VOICE_MODEL=qwen-audio-3.0-realtime-flash`；
- 音色 `CHATBOT_REALTIME_VOICE_NAME=longanqian`；
- `smart_turn` 轮次检测；
- 16kHz、16bit、单声道 PCM 输入和 24kHz、16bit、单声道 PCM 输出；
- AgentScope `RAGMiddleware` 产生的只读 `search_knowledge` Function Calling 工具。

浏览器只允许发送一种事件。`audio` 是 PCM16 字节的 Base64；建议每 20ms 发送 640 字节，
单帧硬上限为 6400 字节，空帧、奇数字节、无效 Base64 和额外字段都会返回协议错误并以
`1008` 关闭。

```json
{"type":"audio.append","audio":"<base64-pcm16>"}
```

服务端公共事件如下：

```json
{"type":"session.ready"}
{"type":"input.speech_started"}
{"type":"input.speech_stopped"}
{"type":"transcript.user.delta","text":"稳定转写","stash":"临时转写"}
{"type":"transcript.user.done","transcript":"用户最终转写"}
{"type":"tool.started"}
{"type":"tool.completed"}
{"type":"transcript.assistant.delta","delta":"助手文本增量"}
{"type":"transcript.assistant.done","transcript":"助手最终转写"}
{"type":"audio.delta","audio":"<base64-24khz-pcm16>"}
{"type":"response.done"}
{"type":"error","code":"voice_service_unavailable","message":"可公开错误文案"}
```

`tool.started/tool.completed` 不包含工具名、参数或结果。模型发出
`response.function_call_arguments.done` 后，后端通过 AgentScope `Toolkit.call_tool`
执行工具，把最终结果作为 `function_call_output` 写回同一百炼会话，并在首轮
`response.done` 后发送一次 `response.create` 生成可朗读回复。百炼原始事件、API Key、
检索参数、证据全文和内部异常均不会进入浏览器。客户端格式错误使用
`invalid_client_event`；上游连接或事件故障统一公开为 `voice_service_unavailable`。
工具自身失败时写回受控错误结果，由模型向用户如实说明，不把异常详情发送到浏览器。
前端必须将 `transcript.user.done`、`transcript.assistant.done` 以及断开前已生成的助手转写
按事件顺序收集。语音会话结束后，客户端清除 assistant-ui 的临时 voice messages，再把
收集结果一次性导入当前 `LocalRuntime` 基础消息分支，且不得再次触发文本模型生成。
该记录只存在于页面线程；刷新恢复和多端同步仍需要独立的服务端会话持久化协议。

## 知识库管理 API

配置 `CHATBOT_MANAGEMENT_API_KEY` 后，`/api/v1/knowledge/*` 全部路由要求
`X-Api-Key` 请求头与密钥恒时比较匹配，否则返回 401；未配置时不要求身份请求头。
浏览器通过 Next.js `/api/knowledge/*` BFF 同源访问这些地址，BFF 在服务端附加
`X-Api-Key`，浏览器不持有密钥。该接口可以创建、修改和删除检索数据，只 应在
本地或受信网络使用，不得直接暴露到公网。

### 知识库

- `GET /api/v1/knowledge/knowledge-bases`：列出全部知识库及文档统计。
- `POST /api/v1/knowledge/knowledge-bases`：创建独立目录和 Qdrant
  collection 的知识库，请求包含 `name` 和 `description`。
- `DELETE /api/v1/knowledge/knowledge-bases/{knowledge_base_id}`：删除一个
  已清空文档的非默认知识库及其独立目录、版本目录和 Qdrant collection，返回 204；
  删除默认知识库或仍有文档的知识库返回 409，不存在返回 404。

### 文档与任务

以下路径前缀统一记为：

```text
/api/v1/knowledge/knowledge-bases/{knowledge_base_id}
```

- `GET {scope}/documents`：返回该知识库的文档、状态、切片汇总、格式和大小限制。
- `POST {scope}/documents?replace=false`：以 multipart `file` 上传单个文档，返回 `202`；
  同知识库同名且未显式替换返回 `409`，不同知识库允许同名。
- `GET {scope}/documents/{document_id}`：读取逻辑文档和最近任务。
- `POST {scope}/documents/{document_id}/reindex`：对当前活动原文件版本重新索引。
- `DELETE {scope}/documents/{document_id}`：异步删除原文件、全部版本、索引和媒体。
- `GET {scope}/jobs/{job_id}`：读取可在重启后恢复的任务状态。

文档状态为 `queued`、`processing`、`ready`、`failed`、`unsupported` 或 `deleting`；
任务操作为 `index`、`reindex`、`rollback` 或 `delete`，状态为 `queued`、`running`、
`succeeded` 或 `failed`。替换失败但旧索引仍可用时，
`has_active_index` 保持为 `true`。

### 切片浏览与编辑

`GET {scope}/documents/{document_id}/chunks?offset=0&limit=20` 从 Qdrant
payload 读取当前活动向量文档，按 `chunk_index` 排序后分页。响应包含最终索引文本、来源、
正文 SHA-256、手工编辑标记、结构元数据和浏览器安全图片引用，不返回 embedding 向量。

`PATCH {scope}/documents/{document_id}/chunks/{chunk_index}` 请求示例：

```json
{"content":"修订后的切片正文","expected_content_hash":"64位小写SHA-256"}
```

接口只编辑活动文本切片，重新生成该切片向量并原子覆盖 Qdrant point。哈希不一致或文档正在
处理时返回 `409`；编辑不会改写原文件。

### 版本历史与回滚

- `GET {scope}/documents/{document_id}/versions`：按时间倒序返回不可变原文件版本、版本号、
  状态和是否可回滚。
- `POST {scope}/documents/{document_id}/versions/{version_id}/rollback`：返回 `202`，后台重新
  解析历史原文件并在成功后切换活动版本。回滚会替换当前索引中的手工切片编辑。

### 召回测试

`POST {scope}/retrieval-tests` 请求示例：

```json
{"query":"库存预警如何设置？","top_k":5,"candidate_top_k":50,"score_threshold":null}
```

该接口不进入 Agent 或回答生成，复用正式检索的查询规范化、Embedding、Qdrant 向量召回和
qwen3-rerank。响应分别提供向量候选和最终结果，包括阶段排名、向量分数、重排分数、切片
内容及阶段耗时；重排失败时 `rerank_status=fallback` 并明确返回向量排序回退结果。
