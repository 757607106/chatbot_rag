# API 说明

当前版本不提供命令行或 HTTP 入口。

应用层的主要调用接口为：

```python
reply = await ChatService(agent).reply("用户问题")
```

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
