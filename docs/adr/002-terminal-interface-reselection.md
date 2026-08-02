# ADR 002：移除 Textual 并重新选择终端交互技术

## 状态

已采纳 prompt_toolkit + Rich；真实终端手工验收待完成。

## 背景

项目曾使用 Textual 构建全屏终端聊天界面，但在真实终端中出现输入卡顿、消息
无法稳定提交、软件光标过粗以及窗口适配异常。单元测试和伪终端测试能够通过，
却不能覆盖用户实际终端与中文输入法的组合，因此继续修改样式或局部限频不能
证明交互链路可靠。

AgentScope 2.0.5 继续负责智能体、RAG 和事件流。终端层必须作为独立协议适配
边界，不得把界面状态或第三方 TUI 类型传入 `services`、`agents` 或 `rag`。

## 决策

删除 Textual CLI、命令入口及只服务于该界面的流式适配。替代实现使用
prompt_toolkit 负责终端原生输入，使用 Rich 负责增量输出和结构化展示。

选型采用两级验证门：

1. 使用 `prompt_toolkit` 验证中文输入、真实光标、提交、换行、异步事件和
   窗口缩放。自动化测试通过可注入输入输出验证提交、换行与历史导航；真实
   终端和中文输入法组合继续作为发布前手工检查。
2. Python 单进程方案使用 AgentScope 原生 `reply_stream` 事件；如果后续真实
   终端验收发现无法修复的核心输入问题，再停止扩展并评估 Bubble Tea v2。

正式展示层使用 Rich `Markdown`、`Panel` 和追加式文本渲染；`Status` 仅用于
输入提示启动前的知识库准备阶段。

> 修订（2026-08）：流式阶段最初只刷新轻量文本、文本块结束后再解析
> Markdown，后改为在 Rich `Live` 视图中实时渲染 Markdown。真实终端验收
> 发现 `Live`/`Status` 与 prompt_toolkit 活动输入提示存在根本冲突：会话
> 控制台在 `patch_stdout` 之前创建、绕过 `StdoutProxy` 直写终端，`Live`
> 的原地重绘序列覆盖输入区且在整个回复期间隐藏终端光标，表现为消息回显
> 丢失（"发了消息没有反应"）和光标显示异常。最终决策：会话期间所有输出
> 改为追加式——控制台在 `patch_stdout` 内创建并写入 `StdoutProxy`，由
> prompt_toolkit 统一安排在提示区上方打印；文本按行追加渲染（Markdown 行
> 逐行渲染、代码围栏与表格聚合、纯文本逐字），回复活动状态移入输入提示区
> 显示。代价是放弃行内原地重绘，换取与持久输入提示完全兼容的渲染路径。

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

- 项目恢复 `chatbot-rag` 和 `python -m chatbot_rag` 两种启动方式。
- CLI 保持为独立协议适配层，核心服务只增加 AgentScope 原生事件流接口。
- 自动化测试不能替代真实终端验收；发布前仍需完成本文列出的手工检查。

## 参考资料

- [prompt_toolkit：输入、中文字符与光标](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/asking_for_input.html)
- [prompt_toolkit：全屏应用](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html)
- [Rich：Status](https://rich.readthedocs.io/en/latest/reference/status.html)
- [Rich：Live Display](https://rich.readthedocs.io/en/latest/live.html)
- [Rich：Markdown](https://rich.readthedocs.io/en/latest/markdown.html)
- [Rich：Panel](https://rich.readthedocs.io/en/latest/panel.html)
- [Bubble Tea v2](https://github.com/charmbracelet/bubbletea/releases)
- [Codex Rust TUI 代码结构](https://github.com/openai/codex/blob/main/codex-rs/README.md)
- [Ink](https://github.com/vadimdemedes/ink)
