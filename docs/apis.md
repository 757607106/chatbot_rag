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
`2`，正常事件顺序如下：

```json
{"version":2,"type":"message_start","message_id":"reply-id"}
{"version":2,"type":"text_delta","message_id":"reply-id","text":"文本增量"}
{"version":2,"type":"image_part","message_id":"reply-id","url":"/api/media/64位资产标识","filename":"操作步骤.png"}
{"version":2,"type":"message_end","message_id":"reply-id","finish_reason":"completed"}
```

`image_part` 只在本次 RAG 检索命中了关联图片，且模型在对应说明位置引用该图片时出现；
事件会紧跟对应的文本段落或列表项，每次回复最多发送 3 张，不会在结束事件前统一追加。
每张图片前必须有自上一张图片后新增的非空正文，连续图片标记只转换第一张。
`url` 必须是同源 `/api/media/<asset_id>`，不会向浏览器公开文档磁盘路径或远程
原始图片地址。前端必须将文字和图片累积为完整 assistant-ui 消息 parts；后续事件
不得覆盖此前图片。

HTTP 响应头发出后的失败通过流内错误表达：

```json
{"version":2,"type":"error","code":"agent_error","message":"可公开错误文案"}
```

错误码为 `agent_error`、`incomplete_stream` 或 `protocol_error`。公共协议发送助手
回复生命周期、文本增量和已脱敏的文档图片引用；AgentScope 思考、工具参数、检索
内部标记和异常细节不会进入浏览器。模型输出的图片标记只有属于本轮检索结果时才会
转换为图片事件，编造、跨轮复用、重复或超过数量上限的标记会被丢弃。前端必须按
`message_id` 校验事件归属。

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
    return await create_rag_agent(settings, knowledge_base)

service = ChatService(create_agent)
conversation = [ConversationTurn(role="user", content="用户问题")]

reply = await service.reply(conversation)

async for event in service.reply_stream(conversation):
    ...
```

`reply_stream` 返回 AgentScope 2.0.5 原生 `AgentEvent`，只允许协议适配层消费。
智能体使用 AgentScope 官方 `agentic` RAG：模型结合当前问题和显式对话历史判断是否调用
只读 `search_knowledge`。工具调用、查询参数和检索原文不会进入公共 NDJSON；若工具结果
含有关联图片，协议层只在内部提取媒体允许列表。

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

## 语音识别

### `POST /api/v1/speech/transcriptions`

使用 `multipart/form-data` 上传名为 `file` 的录音。支持 AAC、FLAC、MP4/M4A、MP3、
Ogg/Opus、WAV 和 WebM，文件不能为空且最大 10 MB。成功响应示例：

```json
{"text":"请查询今天的销售订单。","language":"zh","emotion":"neutral"}
```

识别模型由 `CHATBOT_ASR_MODEL` 控制，默认 `qwen3-asr-flash`；识别语言由
`CHATBOT_ASR_LANGUAGE` 控制，默认 `zh`。模型 API Key 与聊天、嵌入和语音合成共用
服务端 `DASHSCOPE_API_KEY`。音频只在 Python 服务端转换为 Data URL 后调用百炼，
浏览器不持有 API Key。

错误映射：缺少或空录音返回 `422`；格式不支持返回 `415`；超过 10 MB 返回 `413`；
上游识别失败返回 `502`；语音识别服务未装配返回 `503`。浏览器请求 Next.js 同源
`POST /api/speech/transcriptions` BFF，由 BFF 重复执行格式和大小边界校验。

## 语音合成

### `POST /api/v1/speech/tts`

请求体：

```json
{"text":"要朗读的助手回答"}
```

`text` 去除首尾空白后不能为空，最长 20,000 字符，与百炼
`SpeechSynthesizer.call` 当前单次上限一致；额外字段会被拒绝。成功返回
`audio/wav`（24kHz 单声道 16 位完整
WAV）与 `Cache-Control: no-store`。合成模型由 `CHATBOT_TTS_MODEL` 控制，默认
`qwen-audio-3.0-tts-plus`，音色由 `CHATBOT_TTS_VOICE` 控制，默认 `longanlingxin`。

错误映射：文本无效返回 `422`；上游合成失败返回 `502`；语音服务未装配返回 `503`。
浏览器不直接调用该地址，而是请求 Next.js 同源 `POST /api/speech/tts` BFF。

## 知识库管理 API

`/api/v1/knowledge/*` 不要求应用内登录或身份请求头。浏览器通过 Next.js
`/api/knowledge/*` BFF 同源访问这些地址。该接口可以创建、修改和删除检索数据，只应在
本地或受信网络使用，不得直接暴露到公网。

### 知识库

- `GET /api/v1/knowledge/knowledge-bases`：列出全部知识库及文档统计。
- `POST /api/v1/knowledge/knowledge-bases`：创建独立目录和 Qdrant
  collection 的知识库，请求包含 `name` 和 `description`。

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
