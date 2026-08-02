"use client";

import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";

import { ChatGPT } from "@/components/assistant-ui/thread";
import { chatModelAdapter } from "@/features/chat/runtime/chat-model-adapter";

export function Assistant() {
  const runtime = useLocalRuntime(chatModelAdapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="h-dvh">
        <ChatGPT />
      </main>
    </AssistantRuntimeProvider>
  );
}
