"use client";

import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";

import { ChatGPT } from "@/components/assistant-ui/thread";
import { chatModelAdapter } from "@/features/chat/runtime/chat-model-adapter";
import { KnowledgeNavigationLink } from "@/features/knowledge/components/knowledge-navigation-link";

export function Assistant() {
  const runtime = useLocalRuntime(chatModelAdapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="h-dvh">
        <ChatGPT
          sidebarNavigation={<KnowledgeNavigationLink />}
          collapsedSidebarNavigation={<KnowledgeNavigationLink compact />}
          mobileNavigation={<KnowledgeNavigationLink />}
        />
      </main>
    </AssistantRuntimeProvider>
  );
}
