import type { ThreadMessage, ThreadRuntime } from "@assistant-ui/react";

export type VoiceTranscriptRecord = {
  role: "user" | "assistant";
  text: string;
};

type VoiceTranscriptThread = Pick<ThreadRuntime, "export" | "import">;

export class VoiceTranscriptLedger {
  private readonly records: VoiceTranscriptRecord[] = [];
  private assistantDraft = "";

  addUserFinal(text: string): void {
    this.addRecord("user", text);
  }

  updateAssistantDraft(text: string): void {
    this.assistantDraft = text;
  }

  finishAssistant(text?: string): void {
    if (text !== undefined) this.assistantDraft = text;
    this.addRecord("assistant", this.assistantDraft);
    this.assistantDraft = "";
  }

  snapshot(): readonly VoiceTranscriptRecord[] {
    this.finishAssistant();
    return [...this.records];
  }

  private addRecord(role: VoiceTranscriptRecord["role"], text: string): void {
    const normalized = text.trim();
    if (!normalized) return;
    this.records.push({ role, text: normalized });
  }
}

export function commitVoiceTranscript(
  thread: VoiceTranscriptThread,
  records: readonly VoiceTranscriptRecord[],
): void {
  if (records.length === 0) return;

  const repository = thread.export();
  const createdAt = Date.now();
  let parentId = repository.headId ?? null;
  const appended = records.map((record, index) => {
    const id = `voice-${globalThis.crypto.randomUUID()}`;
    const message = createVoiceMessage(record, id, new Date(createdAt + index));
    const item = { parentId, message };
    parentId = id;
    return item;
  });

  thread.import({
    headId: parentId,
    messages: [...repository.messages, ...appended],
  });
}

function createVoiceMessage(
  record: VoiceTranscriptRecord,
  id: string,
  createdAt: Date,
): ThreadMessage {
  const common = {
    id,
    createdAt,
    content: [{ type: "text" as const, text: record.text }],
  };
  if (record.role === "user") {
    return {
      ...common,
      role: "user",
      attachments: [],
      metadata: { custom: { source: "realtime_voice" } },
    };
  }
  return {
    ...common,
    role: "assistant",
    status: { type: "complete", reason: "stop" },
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      custom: { source: "realtime_voice" },
    },
  };
}
