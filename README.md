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

## 交互式终端

项目使用 Rich 渲染状态、Markdown、工具调用面板和流式回复，使用
prompt_toolkit 处理异步输入、历史记录与斜杠命令补全。启动命令：

```bash
chatbot-rag
```

也可以直接运行 Python 模块：

```bash
python -m chatbot_rag
```

输入快捷键和命令：

- `Enter`：发送消息；
- `Esc+Enter`：在当前消息中换行；
- `Esc`：中断当前回复；
- `↑/↓`：浏览历史输入；
- `/help`：显示帮助；
- `/clear`：清空终端；
- `/verbose`：切换是否显示完整工具输入与输出；
- `/exit` 或 `Ctrl+D`：退出。

CLI 使用紧凑的 `user：/ agent：` 对话层级。回复期间仍可继续输入，
后续消息会显示排队确认并按提交顺序处理。每轮回复结束后会显示耗时、token
用量和工具调用次数；工具输入与结果默认合并为一个面板，长内容会截断以保护
页面布局。

输入历史以纯文本保存在 `~/.chatbot_rag/history`。如果问题中包含敏感信息，
应按运行环境的数据保留要求管理或清理该文件。

## 验证

```bash
flake8 src tests
mypy
pytest -q
pytest --cov=chatbot_rag --cov-report=term-missing
```

## 当前范围

工程已经提供 AgentScope 智能体装配、DashScope 聊天与嵌入模型、文档摄取、
Qdrant 持久化、`KnowledgeBase`、`RAGMiddleware`、聊天服务和交互式终端。
HTTP API、检索评测与多租户隔离将在对应需求确认后加入。
