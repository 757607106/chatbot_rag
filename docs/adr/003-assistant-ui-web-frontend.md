# ADR 003：使用 assistant-ui 构建独立 Web 前端

## 状态

已采纳。

## 背景

项目已保留 AgentScope 2.0.5、RAG 和协议无关的 `ChatService`，但当前没有
可对外使用的 HTTP 入口或用户界面。新目标是交付支持流式回复、取消、
错误处理并可逐步扩展工具和附件的 Web 聊天界面，同时不在前端重复智能体编排。

assistant-ui 将聊天界面分为组件、Runtime、后端/智能体、协议与持久化等边界。
对于已有自定义 Python 后端且尚无前端消息 store 的项目，官方将 `LocalRuntime`
定位为由 Runtime 持有对话状态、项目只实现 API 调用的最简路径。

## 决策

1. 在仓库根目录下创建独立 `frontend/` 工程，采用 Next.js App Router、React、
   TypeScript 严格模式、Tailwind CSS、shadcn/ui 和 assistant-ui React。使用 pnpm 并提交
   精确依赖与锁文件。
2. 首个版本使用 assistant-ui `LocalRuntime` 和项目自有 `ChatModelAdapter`。
   UI 组件只通过 Runtime 读写对话状态，适配器是前端与项目 HTTP API 的唯一映射层。
3. Python HTTP 适配层调用 `ChatService.reply_stream`，将 AgentScope 原生事件转换为
   独立、版本化、可取消的 Web 流式协议。不向前端暴露 `AgentEvent` 或 Python 内部类型。
4. Next.js Route Handler 仅在同源部署、Cookie 会话或服务端鉴权需要时担任薄 BFF，
   不实现模型调用、RAG、工具权限或会话持久化。
5. assistant-ui 默认只持有页面内交互状态；持久化会话、用户和租户数据由项目后端
   按权限边界管理。首版不引入 Assistant Cloud。
6. 模型内部思维链不进入公共协议。工具参数和结果由后端允许列表和脱敏后再渲染，
   浏览器不持有模型或存储密钥。
7. 先交付“单会话纯文本发送—流式回复—停止生成—错误重试”竖切片。
   会话列表、持久化、附件、工具 UI 和语音功能在需求确认后逐项接入。

## 备选方案

- **Vite + React**：构建链更轻，但本项目后续需要同源鉴权、部署配置与可选 BFF，
  Next.js 的路由和服务端边界更合适。
- **Vercel AI SDK Runtime**：适合已经使用 AI SDK 的后端，但本项目的模型与智能体
  已由 AgentScope 完整管理，引入它会增加重复抽象和运行时依赖。
- **AssistantTransport 或 AG-UI**：适合后端持有完整智能体状态、需要双向命令或复杂
  人在回路的情况。当前文本 RAG 聊天不需要这些复杂度。
- **assistant-ui Cloud**：能提供托管的会话和历史记录，但会引入外部数据面、鉴权和成本决策，
  当前保持由项目后端管理。
- **全量自研聊天组件**：灵活性高，但会重复消息、Composer、分支、取消、焦点和
  辅助功能状态管理，不符合当前需求的最小设计。

## 影响

- 仓库将增加独立 Node.js/pnpm 工具链与前端 CI，但不改变 Python 包边界。
- 必须先实现稳定的 HTTP 流式协议，才能完成真实前后端联调。
- assistant-ui 和 registry 更新需要精确版本、迁移复核和交互回归。
- `@assistant-ui/react@0.15.1` 的 LocalRuntime 在 Next.js 开发 Strict Mode
  双重挂载下无法稳定绑定初始线程；当前显式关闭 Strict Mode。该设置不是页面定制，
  升级 assistant-ui 后必须通过开发与生产两种模式复测，并在问题消失后恢复。
- 流式协议映射、取消、错误、响应式和键盘交互成为新的验收面。
- 如果未来需要服务端真实时状态、可恢复流或复杂人在回路，需新增 ADR 评估
  `AssistantTransport`、AG-UI 或其他服务端状态协议。

## 参考资料

- [assistant-ui 架构](https://www.assistant-ui.com/docs/architecture)
- [assistant-ui Runtime 选择](https://www.assistant-ui.com/docs/runtimes/pick-a-runtime)
- [assistant-ui LocalRuntime](https://www.assistant-ui.com/docs/runtimes/custom/local-runtime)
- [assistant-ui API 稳定性](https://www.assistant-ui.com/docs/runtimes/concepts/stability)
