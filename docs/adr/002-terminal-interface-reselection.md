# ADR 002：移除 Textual 并重新选择终端交互技术

## 状态

已采纳移除决定；替代技术待原型验收。

## 背景

项目曾使用 Textual 构建全屏终端聊天界面，但在真实终端中出现输入卡顿、消息
无法稳定提交、软件光标过粗以及窗口适配异常。单元测试和伪终端测试能够通过，
却不能覆盖用户实际终端与中文输入法的组合，因此继续修改样式或局部限频不能
证明交互链路可靠。

AgentScope 2.0.5 继续负责智能体、RAG 和事件流。终端层必须作为独立协议适配
边界，不得把界面状态或第三方 TUI 类型传入 `services`、`agents` 或 `rag`。

## 决策

删除 Textual CLI、命令入口及只服务于该界面的流式适配。在替代技术通过真实
终端验收前，项目不提供交互式终端入口。

下一轮选型采用两级验证门：

1. 首先用 `prompt_toolkit` 构建不接入正式入口的最小输入原型，只验证中文
   输入、真实光标、提交、换行、异步事件和窗口缩放。
2. 如果 Python 原型通过全部验收，则继续使用 Python 单进程方案；如果任一
   核心输入指标失败，则停止扩展该原型，改用 Bubble Tea v2 构建独立前端，
   通过本地结构化协议连接 Python AgentScope 后端。

原型不得同时引入 Markdown、工具面板、主题系统等展示功能。输入链路通过后，
再逐项增加流式输出、工具状态、消息排队和样式。

## 候选方案

### prompt_toolkit

- 与 Python 和 `asyncio` 直接集成，不需要跨进程协议。
- 官方支持中文双宽字符、异步输入、可配置真实光标和可注入输入输出的测试。
- 需要自行组织聊天 transcript 和 AgentScope 事件状态，但边界最简单。

### Bubble Tea v2

- 提供高性能声明式渲染、真实终端光标、textarea、viewport 和增强键盘协议。
- Go 前端与 Python 后端需要定义 JSON Lines 或等价的本地双向协议，并处理
  子进程生命周期、打包和跨平台二进制分发。
- 作为 Python 原型失败后的首选，而不是同时维护的第二套正式界面。

### Ratatui

- Codex 当前全屏 TUI 使用 Ratatui，控制力和性能最接近目标体验。
- 文本编辑、Python 通信、跨平台构建和发布成本最高；只有在必须高度复刻
  Codex 且团队接受 Rust 前端时才重新评估。

### Ink

- React 组件模型成熟，并被多个 Agent CLI 使用。
- 会引入 Node.js、React 和 Python 子进程协议；当前项目没有前端复用场景，
  因此不优先采用。

## 验收门槛

任何替代方案必须先通过以下检查，才能接管正式入口：

- 在用户实际使用的终端中，中文输入法提交后按一次 Enter 即发送。
- 使用真实细光标，光标位置与中英文混排、选区和软换行保持一致。
- 终端在 80、120 和 200 列之间缩放时，输入区域立即重排且不越界。
- 连续注入 5,000 个 AgentScope 文本事件时，第二条消息在 100ms 内进入队列。
- 流式输出、键盘读取和界面刷新由独立任务协调，不允许渲染阻塞输入。
- `Esc` 中断、消息排队、粘贴、多行输入和异常恢复均有自动化测试。
- 至少通过 macOS Terminal、iTerm2 和用户实际使用终端的手工验收。
- 完成一次真实 DashScope + AgentScope + RAG 端到端问答。

## 影响

- 当前项目暂时没有可执行聊天命令，但核心服务保持可测试和可复用。
- 新终端界面必须以小型原型开始，不能直接在核心项目中堆叠展示功能。
- 技术选择由真实终端验收结果决定，不再以截图或 headless 测试作为完成标准。

## 参考资料

- [prompt_toolkit：输入、中文字符与光标](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/asking_for_input.html)
- [prompt_toolkit：全屏应用](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html)
- [Bubble Tea v2](https://github.com/charmbracelet/bubbletea/releases)
- [Codex Rust TUI 代码结构](https://github.com/openai/codex/blob/main/codex-rs/README.md)
- [Ink](https://github.com/vadimdemedes/ink)
