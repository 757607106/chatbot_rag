# chatbot_rag

基于 AgentScope 2.0.5 的检索增强聊天机器人。

## 环境要求

- Python 3.11 或更高版本
- 推荐使用 `uv`
- DashScope API Key

## 安装

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements-dev.txt
uv pip install -e . --no-deps
```

配置环境变量：

```bash
export DASHSCOPE_API_KEY="your-api-key"
export CHATBOT_MODEL="qwen-plus"
export CHATBOT_EMBEDDING_MODEL="text-embedding-v4"
export CHATBOT_DOCUMENTS_PATH="tests/docs_test"
export CHATBOT_QDRANT_PATH=".data/qdrant"
```

应用默认递归读取 `tests/docs_test` 中的 `.md`、`.pdf` 和 `.docx` 文件，使用
DashScope Embedding 建立索引，并持久化到本地 Qdrant。内容未变化的文件会
跳过重复索引，`.ipynb` 等不支持的格式会被忽略。远程 Qdrant 可通过
`CHATBOT_QDRANT_URL` 和
`CHATBOT_QDRANT_API_KEY` 配置。

当前版本不提供命令行或 HTTP 入口。AgentScope 智能体、RAG 和聊天服务作为
应用核心保留，对外协议层将在具体需求确认后独立接入。

## 验证

```bash
flake8 src tests
mypy
pytest -q
pytest --cov=chatbot_rag --cov-report=term-missing
```

## 当前范围

工程已经提供 AgentScope 智能体装配、DashScope 聊天与嵌入模型、文档摄取、
Qdrant 持久化、`KnowledgeBase`、`RAGMiddleware` 和聊天服务。HTTP API、检索
评测与多租户隔离将在对应需求确认后加入。
