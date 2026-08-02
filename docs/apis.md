# API 说明

## Web 流式聊天

### `POST /api/v1/chat/stream`

请求体：

```json
{"message":"用户问题"}
```

`message` 会去除首尾空白，不能为空，最大长度为 20,000 个字符；额外字段会被拒绝。
响应媒体类型为 `application/x-ndjson`，每行是一个独立 JSON 事件。公共协议版本固定为
`1`，正常事件顺序如下：

```json
{"version":1,"type":"message_start","message_id":"reply-id"}
{"version":1,"type":"text_delta","message_id":"reply-id","text":"文本增量"}
{"version":1,"type":"message_end","message_id":"reply-id","finish_reason":"completed"}
```

HTTP 响应头发出后的失败通过流内错误表达：

```json
{"version":1,"type":"error","code":"agent_error","message":"可公开错误文案"}
```

错误码为 `agent_error`、`incomplete_stream` 或 `protocol_error`。公共协议当前只发送
助手回复生命周期与文本增量；AgentScope 思考、工具参数和内部异常不会进入浏览器。
前端必须按 `message_id` 校验事件归属，并将 `text_delta` 累积为完整当前文本。

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

## RAG 摄取

```python
async with open_knowledge_base(settings) as knowledge_base:
    summary = await DocumentIngestor(
        knowledge_base,
        ApproxTokenChunker(chunk_size=512, overlap=64),
    ).ingest_directory(settings.documents_path)
```

`IngestionSummary` 分别返回本次建立索引、因内容未变化而跳过，以及从受管目录
移除后同步删除的文档数量。当前支持 `.md`、`.pdf` 和 `.docx` 文件。
