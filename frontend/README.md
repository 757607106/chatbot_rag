# chatbot_rag Web 前端

本目录是独立的 Next.js 与 assistant-ui 工程。前端使用 assistant-ui
`LocalRuntime` 管理页面内对话状态，通过 Next.js BFF 消费 Python API
的版本化 NDJSON 流。

页面组件直接同步自 assistant-ui 官方
[ChatGPT demo](https://github.com/assistant-ui/assistant-ui/blob/main/apps/docs/components/examples/chatgpt.tsx)；
项目只在 `features/chat/` 中维护后端协议解析和 Runtime 适配，不另建聊天视觉层。

## 环境要求

- Node.js 22
- pnpm 10.25.0
- 已启动的 `chatbot_rag` Python API

## 配置

复制 `.env.example` 为 `.env.local`，并根据实际部署地址设置：

```text
CHATBOT_API_URL=http://127.0.0.1:8000/api/v1/chat/stream
```

该变量只在 Next.js 服务端读取，不会暴露给浏览器。

## 本地开发

先在仓库根目录启动 Python API：

```bash
.venv/bin/uvicorn chatbot_rag.services.api:create_app --factory --reload
```

再启动前端：

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

打开 [http://localhost:3000](http://localhost:3000)。

## 验证

```bash
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```
