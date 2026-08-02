# API 说明

当前版本提供交互式命令行入口，不提供 HTTP 入口：

```bash
chatbot-rag
# 或
python -m chatbot_rag
```

CLI 启动时加载环境配置、同步文档索引并进入对话。`/help`、`/clear`、
`/verbose` 和 `/exit` 由终端层处理，不会发送给智能体。`/verbose` 控制
工具面板是否截断长输入和输出，开启时会重放最近一次被截断的工具面板，
不改变 AgentScope 工具执行行为。

应用层的主要调用接口为：

```python
reply = await ChatService(agent).reply("用户问题")
```

流式调用接口为：

```python
async for event in ChatService(agent).reply_stream("用户问题"):
    ...
```

该接口透传 AgentScope 2.0.5 的 `AgentEvent`，协议适配层可分别处理文本、
思考、工具调用、工具结果和回复生命周期事件。

RAG 启动和摄取接口为：

```python
async with open_knowledge_base(settings) as knowledge_base:
    summary = await DocumentIngestor(
        knowledge_base,
        ApproxTokenChunker(chunk_size=512, overlap=64),
    ).ingest_directory(settings.documents_path)
```

`IngestionSummary` 分别返回本次建立索引、因内容未变化而跳过，以及从受管目录
移除后同步删除的文档数量。当前支持 `.md`、`.pdf` 和 `.docx` 文件。

新增 HTTP API 时，路由只负责协议转换、校验和错误映射，并调用应用服务；
不得在路由中直接创建模型、管理 Qdrant 生命周期或实现文档摄取逻辑。
