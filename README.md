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
export CHATBOT_RERANK_MODEL="qwen3-rerank"
export CHATBOT_RERANK_CANDIDATE_TOP_K="50"
export CHATBOT_DOCUMENTS_PATH="tests/docs_test"
export CHATBOT_KNOWLEDGE_DOCUMENTS_ROOT_PATH=".data/knowledge/documents"
export CHATBOT_DOCUMENT_VERSIONS_PATH=".data/knowledge/versions"
export CHATBOT_KNOWLEDGE_CATALOG_PATH=".data/knowledge/catalog.sqlite3"
export CHATBOT_MEDIA_PATH=".data/media"
export CHATBOT_REMOTE_IMAGE_HOSTS="alidocs.oss-cn-zhangjiakou.aliyuncs.com"
export CHATBOT_QDRANT_PATH=".data/qdrant"
export CHATBOT_MAX_UPLOAD_MB="50"
```

`tests/docs_test/` 是本地私有知识目录，已被 Git 忽略，其中的业务文档不会上传到
代码仓库。全新克隆项目后需要先创建该目录，或将 `CHATBOT_DOCUMENTS_PATH` 指向其他
已存在的本地文档目录：

```bash
mkdir -p tests/docs_test
```

应用默认递归读取 `tests/docs_test` 中的 `.md`、`.markdown`、`.txt`、`.pdf`、
`.docx`、`.pptx`、`.xls` 和 `.xlsx` 文件，使用 DashScope Embedding 建立索引，
并持久化到本地 Qdrant。每个文本块会携带文档来源；Markdown 保留标题路径，PDF
保留页码，PPTX 保留幻灯片序号，Excel 保留工作表名。查询时先召回 50 个向量候选，
再由 `qwen3-rerank` 按问题的全部显式条件精排后向模型提供最终 Top 5。内容未变化的
文件会跳过重复索引，旧式 `.doc`、`.ppt` 及 `.ipynb` 等不支持的格式会被忽略。
Markdown 外链图片、Word 内嵌图片和 PDF 页内图片会登记到媒体仓库，并在回答采用
关联文本时紧跟对应说明显示，不会把全部检索图片统一堆到消息末尾。PPTX 和 Excel
当前只索引文本与表格，不抽取其中的图片。
远程 Qdrant 可通过
`CHATBOT_QDRANT_URL` 和
`CHATBOT_QDRANT_API_KEY` 配置。

智能体使用 AgentScope `RAGMiddleware` 的 `agentic` 模式，并把官方
`search_knowledge` 注册到 `Toolkit`。涉及项目资料、产品功能和操作步骤的问题由模型
自主调用知识库检索；明确无关的通用问答、写作或翻译任务不执行 Embedding、Qdrant
和重排序。知识库相关问题检索无结果时必须明确拒答，不得用模型常识补全私有事实。

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
`POST /api/v1/chat/stream`，并把版本化 NDJSON 文本和图片累积为 assistant-ui
`LocalRuntime` 消息。图片通过同源 `/api/media/<asset_id>` BFF 读取，浏览器不会
接触原始文件路径或远程源地址。

左侧栏的“知识库”入口提供无需登录的多知识库管理后台。后台支持知识库创建与切换、
上传、显式同名替换、异步索引状态、
单切片手工编辑、原文件版本回滚、重新索引、删除以及向量召回/重排序测试。每个新增知识库
在 `CHATBOT_KNOWLEDGE_DOCUMENTS_ROOT_PATH` 下使用独立目录和独立 Qdrant collection；
默认知识库继续使用 `CHATBOT_DOCUMENTS_PATH` 和 `CHATBOT_KNOWLEDGE_COLLECTION`，不会搬迁
既有数据。版本文件和控制面状态分别持久化到 `CHATBOT_DOCUMENT_VERSIONS_PATH` 与
`CHATBOT_KNOWLEDGE_CATALOG_PATH`。

当前知识库后台不提供内置身份验证，只适用于本地开发或受信网络。部署时不得把管理 API
直接暴露到公网；如需远程访问，应在应用外部增加网络或身份访问控制。

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
assistant-ui Web 前端。当前 Web 竖切片保证单进程单会话的文本发送、流式回复、
相关文档图片、取消与公开错误；服务端会话隔离、持久化、用户上传附件和工具事件
将在协议明确后单独实现。
