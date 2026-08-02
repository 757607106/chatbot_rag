"use client";

import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { useRouter } from "next/navigation";

import { CloneThreadShell } from "@/components/assistant-ui/clone-thread-shell";
import { chatModelAdapter } from "@/features/chat/runtime/chat-model-adapter";
import { KnowledgeNavigationLink } from "@/features/knowledge/components/knowledge-navigation-link";
import { KnowledgeWorkspace } from "@/features/knowledge/components/knowledge-workspace";

export function KnowledgeAssistant() {
  const runtime = useLocalRuntime(chatModelAdapter);
  const router = useRouter();

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="h-dvh">
        <CloneThreadShell
          sidebarNavigation={<KnowledgeNavigationLink active />}
          collapsedSidebarNavigation={<KnowledgeNavigationLink compact active />}
          mobileNavigation={<KnowledgeNavigationLink active />}
          onThreadNavigate={() => router.push("/")}
        >
          <KnowledgeWorkspace />
        </CloneThreadShell>
      </main>
    </AssistantRuntimeProvider>
  );
}
