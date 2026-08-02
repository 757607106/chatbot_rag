# API 说明

## Web 流式聊天

### `POST /api/v1/chat/stream`

请求体：

```json
{"message":"用户问题"}
```

`message` 会去除首尾空白，不能为空，最大长度为 20,000 个字符；额外字段会被拒绝。
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
图片首次访问时由后端从 `CHATBOT_REMOTE_IMAGE_HOSTS` 允许的 HTTPS 主机下载，并在
校验响应状态、MIME、文件签名和 10 MB 上限后缓存。响应使用
`Content-Disposition: inline`、`X-Content-Type-Options: nosniff` 和私有缓存头。

浏览器不直接调用该地址，而是请求 Next.js 同源 `GET /api/media/{asset_id}` BFF。
未知标识返回 404；远程图片暂时无法取得返回 502。

当前后端复用一个有状态 AgentScope 智能体，并用锁串行化回复，因此仅适用于单进程、
单会话竖切片。引入多用户前必须先增加服务端会话标识与隔离，不得依赖前端线程 ID
隐式隔离智能体记忆。

## 应用服务

非 HTTP 调用可直接使用：

```python
reply = await ChatService(agent).reply("用户问题")

async for event in ChatService(agent).reply_stream("用户问题"):
    ...
```

`reply_stream` 返回 AgentScope 2.0.5 原生 `AgentEvent`，只允许协议适配层消费。
智能体使用 `agentic` RAG：模型仅在判断问题需要项目知识时调用只读
`search_knowledge`。工具调用、查询参数和检索原文不会进入公共 NDJSON；若检索结果
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
