# 《chatbot_rag 开发项目规范》

## 零、技术基线与官方文档

1. **后端基线**：本项目以 `AgentScope 2.0.5` 为开发和验收基线，Python 版本必须为 `3.11` 或更高版本。
2. **前端基线**：Web 客户端采用 Next.js App Router、React、TypeScript 严格模式、assistant-ui React、Tailwind CSS 和 shadcn/ui，统一使用 `pnpm`。前端工程创建后，`frontend/package.json` 和 `frontend/pnpm-lock.yaml` 是唯一版本基线。
3. **官方文档**：[AgentScope 2.0.5 中文文档](https://docs.agentscope.io/versions/2.0.5/zh)、[assistant-ui 文档](https://www.assistant-ui.com/docs)、[Next.js 文档](https://nextjs.org/docs)。
4. 开发 AgentScope 相关功能前，必须优先查阅上述固定版本文档，并遵循文档中的模块路径、公开 API、异步接口和生命周期约定。
5. 开发 assistant-ui 相关功能前，必须先核对锁定版本的官方文档、迁移指南和稳定性标记；不得根据旧示例推测 API，不得在未隔离的业务代码中直接使用 `unstable_`、`experimental_` 或内部 API。
6. 禁止混用 AgentScope 1.x、其他 2.x 版本或开发版文档中的 API。若本地行为与文档不一致，应先核对已安装版本和官方发布说明，不得用兼容性补丁掩盖版本错误。
7. 升级 AgentScope、Next.js、React 或 assistant-ui 必须作为独立变更处理，同时更新依赖锁、架构文档、兼容性测试和必要的迁移说明。

## 一、工程结构与模块化规范

### 1. 推荐目录结构

项目采用 `src layout`。最外层 `chatbot_rag/` 是仓库目录，不参与 Python 导入；`src/chatbot_rag/` 是应用源码包，对应代码中的 `import chatbot_rag`。两者同名但职责不同，不能将源码直接作为 `src.agents` 或 `agents` 等通用顶层包导入。

Web 前端是同仓库内的独立 TypeScript 工程，固定放在 `frontend/`。不得将 Node.js 依赖、Next.js 配置或浏览器代码混入 Python 源码包。

```text
chatbot_rag/                         # 仓库根目录，不是 Python 包
├── src/
│   └── chatbot_rag/                  # Python 源码包：import chatbot_rag
│       ├── __init__.py
│       ├── agents/                   # 智能体定义与编排
│       │   ├── __init__.py
│       │   └── rag_agent.py
│       ├── tools/                    # AgentScope 工具实现
│       │   ├── __init__.py
│       │   └── knowledge_search.py
│       ├── models/                   # 模型与凭据的创建、配置；按需创建
│       │   ├── __init__.py
│       │   └── model_factory.py
│       ├── rag/                      # 文档处理、索引与检索领域逻辑
│       │   ├── __init__.py
│       │   ├── document_loader.py
│       │   ├── index_manager.py
│       │   └── retriever.py
│       ├── memory/                   # 会话状态与长期记忆集成
│       │   ├── __init__.py
│       │   └── session_store.py
│       ├── services/                 # 应用用例与对外服务入口
│       │   ├── __init__.py
│       │   ├── chat_service.py
│       │   └── api/                  # HTTP 路由、依赖注入与异常映射
│       │       ├── __init__.py
│       │       └── chat_routes.py
│       ├── schemas/                  # API 请求、响应及跨层数据结构
│       │   ├── __init__.py
│       │   └── chat_schema.py
│       ├── config/                   # 配置加载与校验
│       │   ├── __init__.py
│       │   └── settings.py
│       └── main.py                   # 应用装配与启动入口
├── frontend/                           # Next.js Web 客户端；按需创建
│   ├── package.json                    # 前端命令、精确依赖与 Node/pnpm 约束
│   ├── pnpm-lock.yaml                  # 必须提交的唯一前端依赖锁
│   ├── components.json                 # shadcn/assistant-ui registry 配置
│   ├── next.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── app/                        # 路由、layout 和应用装配
│       │   ├── api/chat/route.ts      # 可选同源 BFF；仅代理与鉴权
│       │   └── page.tsx
│       ├── components/
│       │   ├── assistant-ui/         # assistant-ui registry 组件源码
│       │   └── ui/                   # 通用 shadcn 视觉原语
│       ├── features/chat/
│       │   ├── components/           # 业务聊天组件
│       │   ├── runtime/              # assistant-ui Runtime 及消息映射
│       │   ├── api/                  # 聊天请求、流解析与取消
│       │   └── schemas/              # 前端边界数据类型
│       └── styles/                     # 设计 token 与全局样式
├── tests/
│   ├── unit/                         # 不依赖真实外部服务的快速测试
│   ├── integration/                  # 模型、存储、API 等集成测试
│   └── conftest.py
├── docs/
│   ├── architecture.md
│   ├── apis.md
│   └── changelog.md
├── requirements.txt                  # 运行时依赖
├── requirements-dev.txt              # 测试、类型检查和代码质量依赖
└── .gitignore
```

目录和文件按实际需求创建，禁止为了匹配示例而保留没有职责的空模块。

### 2. 模块边界

1. `agents/` 只负责智能体配置和任务编排，不直接实现文档解析、数据库访问或 HTTP 路由。
2. `tools/` 只放可由 AgentScope `Toolkit` 调度的工具；普通领域服务不能因为会被智能体调用就全部包装成工具。
3. `rag/` 承载文档摄取、切分、索引、召回和重排等 RAG 领域逻辑，避免散落在智能体或路由中。
4. `models/` 优先复用 AgentScope 2.0.5 已提供的模型与凭据类，只负责实例创建和项目级配置；没有额外行为时不得重复封装官方类。
5. `memory/` 负责会话状态和记忆持久化，不包含智能体编排逻辑。
6. `services/` 负责组合用例；`services/api/` 只处理协议适配、参数校验、鉴权调用和错误映射。
7. `schemas/` 仅定义跨边界的数据结构，不承载业务逻辑。
8. `config/` 统一读取和校验配置。业务模块不得散落读取环境变量，也不得在代码中硬编码密钥。
9. 禁止循环依赖。跨模块共享的低层通用逻辑可放入 `utils/`，但文件必须按具体职责命名，且不得反向依赖 `agents/` 或 `services/`。
10. `frontend/src/app/` 只负责 Next.js 路由、layout、服务端/客户端边界和组装，不得实现消息流解析或对话领域逻辑。
11. `frontend/src/components/assistant-ui/` 保存 registry 拉取后可审查的组件源码；`components/ui/` 保存通用视觉原语。两者均不直接请求后端，不放项目特定的 RAG 或鉴权逻辑。
12. `frontend/src/features/chat/runtime/` 是 assistant-ui Runtime 与本项目 API 之间的唯一消息映射边界；`api/` 只处理请求、流解析、取消和错误分类；`components/` 只消费 Runtime 状态并渲染交互。
13. Next.js Route Handler 只在需要同源代理、Cookie 会话或服务端鉴权时作为 BFF，不得在 TypeScript 层重复智能体、RAG、模型调用或持久化业务逻辑。

### 3. 文件夹及文件命名规范

1. Python 包、目录、模块、函数、方法和变量统一使用小写 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
2. 名称必须表达业务职责，使用英文单词，禁止拼音、无意义缩写以及空格、连字符或大小写混合的 Python 文件名。
3. 同类包统一使用复数名称，如 `agents/`、`tools/`、`services/`、`schemas/`；具体模块使用单一职责名称。
4. 智能体文件使用 `<capability>_agent.py`，如 `rag_agent.py`、`query_rewrite_agent.py`。
5. 工具文件按能力命名，如 `knowledge_search.py`、`document_reader.py`；服务文件使用 `<domain>_service.py`；数据结构文件使用 `<domain>_schema.py`。
6. 测试文件使用 `test_<module>.py`，测试函数使用 `test_<expected_behavior>`；目录结构应尽量镜像被测源码。
7. 避免 `helper.py`、`common.py`、`misc.py`、`custom_tool.py`、`data_processor.py` 等职责模糊的名称。确有通用代码时，使用 `json_codec.py`、`retry_policy.py` 等具体名称。
8. `__init__.py` 只用于声明包边界和稳定的公共导出，不放业务实现或产生导入副作用。
9. 单个模块应保持单一职责；当文件同时包含多个独立领域概念时，应按职责拆分，而不是按文件行数机械拆分。
10. TypeScript 目录和文件使用小写 `kebab-case`，React 组件、类型和接口使用 `PascalCase`，函数和变量使用 `camelCase`，Hook 使用 `use<Capability>`，常量使用 `UPPER_SNAKE_CASE`。registry 生成文件保留上游命名。
11. 前端测试文件使用 `*.test.ts` 或 `*.test.tsx`，Playwright 端到端测试使用 `*.spec.ts`；测试就近放置或按 `frontend/tests/` 中与源码对应的结构放置，全项目保持一致。

## 二、代码设计规范

### 1. 使用 AgentScope 2.0.5 原生能力

1. 智能体应按照 2.0.5 官方 API 使用或扩展 `agentscope.agent.Agent`，优先通过组合模型、`Toolkit`、上下文和中间件实现需求。禁止强制继承不存在于该版本公开 API 的类。
2. 工具统一通过 `agentscope.tool.Toolkit` 装配：
   - 优先使用 AgentScope 内置工具；
   - 简单函数工具使用官方函数包装能力；
   - 需要自定义 schema、权限或执行行为的复杂工具继承 `agentscope.tool.ToolBase`。
3. 日志、追踪、输入改写、访问控制等横切能力使用 AgentScope 中间件及其 hook，不得侵入智能体主循环硬编码。
4. 禁止引入 LangChain 等第二套智能体编排框架。HTTP、存储、解析、可观测性等支撑库可在确有需要时使用，但必须说明用途、声明依赖并避免取代 AgentScope 的核心能力。

### 2. assistant-ui 与聊天协议设计

1. assistant-ui 仅负责前端组件、交互状态和 Runtime 适配，AgentScope 继续是唯一智能体编排层。不得为接入 UI 而引入 Vercel AI SDK、LangChain 或 LangGraph 重复模型调用和编排。
2. 首个版本使用 assistant-ui `LocalRuntime` 和项目自有 `ChatModelAdapter`，由 Runtime 管理页面内消息、编辑、重试、分支和取消状态。只有当后端需要成为完整对话状态真实源时，才独立评估 `AssistantTransport`、AG-UI 或 `ExternalStoreRuntime`。
3. `ChatModelAdapter` 只调用项目 HTTP 边界，将经过版本化的协议事件转换为 assistant-ui 消息 part。不得将 AgentScope `AgentEvent`、Python 类名、模型 SDK 对象或 assistant-ui 内部类型直接穿透另一边。
4. 流式协议必须定义开始、文本增量、可公开进度、工具调用状态、完成和错误等受控事件，并支持 `AbortSignal` 贯穿至后端。适配器必须正确累积增量，向 `LocalRuntime` 返回完整当前内容，不得在流中遗失早先的文本或工具 part。
5. 浏览器不得持有模型、Qdrant 或其他服务端密钥，不得绕过本项目 API 直连模型供应商。同源 BFF 不记录完整提示词、文档内容、凭据或未脱敏工具结果。
6. 不展示模型隐藏思维链或 AgentScope 内部推理原文。UI 只能渲染后端明确标记为可公开的阶段状态或简短摘要。工具参数和结果必须先经后端允许列表与脱敏，权限操作仍由后端执行。
7. Markdown、引用、链接和附件是不可信输入。前端必须禁止未经消毒的 HTML，限制 URL 协议，并显式处理空流、协议不完整、超时、用户取消和服务端错误。
8. 附件功能必须同时在浏览器和服务端校验数量、大小、MIME 类型和文件名。大文件应上传至服务端或对象存储后传递受控引用，不得默认将大文件 Base64 化后放入消息。
9. 会话持久化与 UI 渲染分离。未经独立决策不引入 Assistant Cloud；未登录用户、租户、会话的持久化数据必须由项目后端按权限边界管理。

### 3. 前端体验与视觉规范

1. 实现页面前先明确用户、使用场景、信息密度和一个清晰的视觉方向，并将字体、色彩、间距、圆角、阴影和动效收敛为 CSS 变量或设计 token。禁止无产品语义地复制默认示例页。
2. 优先组合 assistant-ui primitives 和项目 token；registry 组件拉取后视为项目源码，修改时必须保持键盘交互、焦点管理、ARIA 语义和 Runtime 状态契约，不得复制一套平行聊天状态。
3. 必须覆盖空会话、正在生成、正在执行工具、完成、用户取消、网络中断、可重试错误和无数据状态。流式输出期间不得锁死页面，必须提供停止生成操作。
4. 默认提供简体中文文案并设置正确的文档语言；用户可见文案应集中管理，不得在多个组件中散落重复字符串。只有确认多语言需求后才引入完整 i18n 框架。
5. 布局必须在手机、平板和桌面宽度下可用，输入框不得被软键盘或安全区遮挡。长消息、代码块、表格、引用和超长单词不得撑破主容器。
6. 所有核心操作必须支持键盘，具有可见焦点、语义化标签、可读错误文案和足够对比度。动效要尊重 `prefers-reduced-motion`，流式文本的辅助技术通知必须节流，避免逐 token 宣读。

### 4. 避免重复逻辑

1. 公共逻辑应提取到职责明确的领域模块、基类或工具函数中，禁止在多个智能体中复制实现。
2. 不得为复用而创建无明确边界的“万能工具类”或过度抽象；只有出现稳定的共同职责时才提取公共模块。

### 5. 架构优先，拒绝临时补丁

1. 遇到兼容性问题时，应定位版本、配置、接口或数据边界的根本原因。
2. 禁止使用吞掉异常、静默降级、无说明的 monkey patch 等方式掩盖问题。
3. 升级 AgentScope、替换存储或调整公共接口等架构变更，必须单独评审并记录迁移和回滚方案。

### 6. 中文注释与可维护性要求（强制）

1. 项目自有代码中的行内注释、块注释和 docstring 必须使用中文；类名、函数名、参数名、协议名、第三方 API 名称等技术标识符可保留英文。新增或修改代码时，变更范围内已有的英文注释也必须同步改为中文。`components/assistant-ui/` 与 `components/ui/` 中原样同步的官方 registry 源码可保留上游注释，以便后续逐行比对；项目新增或改写的注释仍必须使用中文。
2. 注释应重点说明设计原因、业务规则、边界条件和非显而易见的取舍，禁止逐行翻译代码或添加没有信息量的注释。代码行为变化时必须同步更新注释，过期或与实现冲突的注释视为代码缺陷。
3. 整体项目必须保持可维护、可测试和可迭代：模块职责单一、依赖方向清晰、公共接口稳定、控制流易读。新增功能必须放入职责匹配的模块，并同步补充必要的测试和文档。
4. 坚持满足当前明确需求的最小设计，禁止为尚未确认的需求预建抽象层、扩展点、配置项、兼容分支或通用框架。只有存在清晰且稳定的复用场景时才允许抽象，禁止过度设计。
5. 禁止遗留未使用的函数、类、变量、导入、依赖、配置、不可达分支、注释掉的旧实现和无任务关联的 `TODO`。废弃实现应由版本控制保留历史，不得继续留在源码中。
6. 禁止保留无职责的空目录、空壳模块、临时脚本、备份文件、调试文件、重复实现和生成产物；仅用于声明 Python 包边界的 `__init__.py` 除外。
7. 每次变更完成前必须检查本次涉及的代码和文件，确认命名与职责一致、没有重复或无用内容，并通过代码风格、类型检查和相关测试后方可交付。

## 三、依赖与版本管理

1. Python 运行时依赖写入 `requirements.txt`，开发依赖写入 `requirements-dev.txt`，所有直接依赖必须显式声明并固定到可重复安装的版本。
2. AgentScope 固定为：

```text
agentscope[full]==2.0.5
```

3. `mcp[cli]`、模型 SDK、数据库驱动等依赖仅在项目实际使用对应能力时添加，禁止预先堆叠无用依赖。
4. 禁止在代码中直接 `import` 未声明的第三方库。
5. 依赖升级必须记录变更原因，并执行完整测试和 AgentScope 兼容性检查。
6. 前端直接依赖必须在 `frontend/package.json` 中声明精确版本，提交 `pnpm-lock.yaml`，并通过 `packageManager` 和 `engines` 固定 pnpm 与 Node.js 约束。禁止提交 `^`、`~`、`latest`、Git 分支或未锁定 workspace 依赖。
7. 前端只使用 pnpm，不得提交 `package-lock.json`、`yarn.lock` 或 `bun.lock`。`npx assistant-ui@latest` 仅可在人工初始化时使用，生成后必须立即检查差异、锁定实际版本；CI 和可重复脚本禁止使用 `@latest`。
8. assistant-ui registry 组件是可审查的项目源码，不是运行时远程依赖。执行 registry 更新前必须检查官方迁移说明，更新后必须复核项目定制和交互回归。

## 四、测试与质量保障

1. 单元测试覆盖率目标不低于 80%，重点覆盖：
   - 智能体配置、ReAct 流程和中间件行为；
   - 工具调用、权限检查和异常传播；
   - RAG 摄取、检索及边界条件；
   - 会话状态、记忆持久化与恢复；
   - 前端协议解析、增量累积、Runtime 映射、取消和错误分类。
2. 使用 `pytest` 和 `pytest-asyncio` 编写测试；单元测试不得调用真实模型或外部服务，应使用边界替身。
3. 集成测试覆盖至少一条完整聊天链路，并验证 AgentScope 2.0.5 的关键导入路径和接口契约。
4. 前端单元与组件测试使用 Vitest 和 Testing Library，不调用真实模型或外部服务；通过可控 `fetch`/`ReadableStream` 替身验证分块边界、乱序/中断、HTTP 错误和用户取消。
5. Playwright 端到端测试至少覆盖发送消息、流式回复、停止生成、错误重试、Markdown/引用渲染和移动端核心布局；增加工具、附件或会话列表时，必须同步增加对应链路。
6. 前端工程创建后，CI 每次提交至少执行：
   - 代码风格检查；
   - `mypy` 类型检查；
   - `pytest -q`；
   - AgentScope 版本与兼容性检查；
   - `pnpm --dir frontend lint`；
   - `pnpm --dir frontend typecheck`；
   - `pnpm --dir frontend test`；
   - `pnpm --dir frontend build`；
   - 关键 Playwright 端到端测试。
7. 测试失败不得通过删除断言、扩大异常捕获或无理由跳过测试解决。

## 五、文档与维护规范

1. 所有公共模块、类和方法必须提供类型注解，并编写遵循 Google 风格的 docstring。
2. 公共 TypeScript 函数、组件 props、协议数据和 Runtime 映射必须具有显式类型。注释与 TSDoc 同样使用中文，只解释非显而易见的约束和取舍。
3. 重大逻辑或模块边界变更必须同步更新 `docs/architecture.md`；公共 API 变更更新 `docs/apis.md`；用户可感知的版本变化更新 `docs/changelog.md`。
4. 重要架构取舍应记录背景、备选方案、最终决策及影响，必要时在 `docs/adr/` 新增 ADR。
5. 提交信息必须清晰描述变更内容；项目启用 Jira、Trello 等任务系统时，提交或 PR 应关联对应任务 ID。

## 六、协作与代码审查

1. 所有代码合并前必须通过 Code Review，重点检查：
   - 是否符合 AgentScope 2.0.5 官方接口；
   - 是否符合当前锁定版本的 assistant-ui 公开 API 与 Runtime 边界；
   - 模块边界和命名是否清晰；
   - 是否存在重复逻辑、未声明依赖或不必要的框架替代；
   - 流式回复、取消、错误、工具和空状态是否完整；
   - 是否符合响应式、键盘可用性、敏感数据脱敏与不可信内容渲染要求；
   - 测试和文档是否与变更同步。
2. 禁止直接推送受保护的主分支，必须通过功能分支和 PR 合并。
3. 不得在功能变更中夹带无关的大规模重构；架构重构应独立提交和评审。

## 七、执行建议

1. 项目初始化时按上述结构创建最小必要目录，不创建尚未使用的层。
2. 配置 pre-commit，在本地执行格式、静态检查和快速单元测试。
3. 定期扫描依赖、测试覆盖率、循环依赖和职责模糊模块，并把问题纳入技术债务清单。
4. 创建前端时只在 `frontend/` 内运行 assistant-ui/shadcn 初始化命令，先完成“单会话纯文本发送—流式回复—取消—错误重试”的端到端竖切片，再根据明确需求添加会话列表、附件、工具 UI、语音或持久化。
