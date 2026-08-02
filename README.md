# chatbot_rag

基于 AgentScope 2.0.5 的检索增强聊天机器人。

## 环境要求

- Python 3.11 或更高版本
- 推荐使用 `uv`
- DashScope API Key
- Node.js 22 与 pnpm 10.25.0

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

## 启动 Web 对话

先启动 Python 流式 API：

```bash
uvicorn chatbot_rag.services.api.application:create_app --factory --reload
```

再启动 assistant-ui 前端：

```bash
cp frontend/.env.example frontend/.env.local
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

浏览器访问 `http://127.0.0.1:3000`。前端采用 assistant-ui 官方 ChatGPT demo
组件，通过同源 `/api/chat` BFF 转发到 Python
`POST /api/v1/chat/stream`，并把版本化 NDJSON 文本增量累积为 assistant-ui
`LocalRuntime` 消息。

## 验证

```bash
flake8 src tests
mypy
pytest -q
pytest --cov=chatbot_rag --cov-report=term-missing
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

## 当前范围

工程已经提供 AgentScope 智能体装配、DashScope 聊天与嵌入模型、文档摄取、
Qdrant 持久化、`KnowledgeBase`、`RAGMiddleware`、流式 HTTP API 和
assistant-ui Web 前端。当前 Web 竖切片只保证单进程单会话的纯文本发送、流式回复、
取消与公开错误；服务端会话隔离、持久化、附件和工具事件将在协议明确后单独实现。
