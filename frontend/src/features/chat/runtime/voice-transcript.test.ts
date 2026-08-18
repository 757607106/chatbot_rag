import type { ThreadMessage } from "@assistant-ui/react";
import { describe, expect, it, vi } from "vitest";

import {
  commitVoiceTranscript,
  VoiceTranscriptLedger,
} from "@/features/chat/runtime/voice-transcript";

describe("VoiceTranscriptLedger", () => {
  it("按对话顺序保存最终用户文本和助手文本", () => {
    const ledger = new VoiceTranscriptLedger();

    ledger.addUserFinal(" 如何安装打印机？ ");
    ledger.updateAssistantDraft("请先打开设置");
    ledger.finishAssistant("请先打开设置，再选择打印机。");

    expect(ledger.snapshot()).toEqual([
      { role: "user", text: "如何安装打印机？" },
      { role: "assistant", text: "请先打开设置，再选择打印机。" },
    ]);
  });

  it("会话中断时保留已经生成的助手文字", () => {
    const ledger = new VoiceTranscriptLedger();
    ledger.addUserFinal("继续");
    ledger.updateAssistantDraft("正在说明第一步");

    expect(ledger.snapshot()).toEqual([
      { role: "user", text: "继续" },
      { role: "assistant", text: "正在说明第一步" },
    ]);
  });
});

describe("commitVoiceTranscript", () => {
  it("把语音记录接到基础消息分支且不触发文本模型", () => {
    const baseMessage = {
      id: "base-assistant",
      role: "assistant",
      content: [{ type: "text", text: "已有回复" }],
      status: { type: "complete", reason: "stop" },
      createdAt: new Date(1),
      metadata: {
        unstable_state: null,
        unstable_annotations: [],
        unstable_data: [],
        steps: [],
        custom: {},
      },
    } as const satisfies ThreadMessage;
    const repository = {
      headId: baseMessage.id,
      messages: [{ parentId: null, message: baseMessage }],
    };
    const importRepository = vi.fn();
    const thread = {
      export: () => repository,
      import: importRepository,
    };

    commitVoiceTranscript(thread, [
      { role: "user", text: "语音问题" },
      { role: "assistant", text: "语音回答" },
    ]);

    const committed = importRepository.mock.calls[0]?.[0];
    expect(committed.messages).toHaveLength(3);
    expect(committed.messages[1].parentId).toBe("base-assistant");
    expect(committed.messages[1].message).toMatchObject({
      role: "user",
      content: [{ type: "text", text: "语音问题" }],
      metadata: { custom: { source: "realtime_voice" } },
    });
    expect(committed.messages[2].parentId).toBe(committed.messages[1].message.id);
    expect(committed.messages[2].message).toMatchObject({
      role: "assistant",
      content: [{ type: "text", text: "语音回答" }],
      status: { type: "complete", reason: "stop" },
    });
    expect(committed.headId).toBe(committed.messages[2].message.id);
  });

  it("没有有效转写时不改写消息仓库", () => {
    const thread = {
      export: vi.fn(),
      import: vi.fn(),
    };

    commitVoiceTranscript(thread, []);

    expect(thread.export).not.toHaveBeenCalled();
    expect(thread.import).not.toHaveBeenCalled();
  });
});
