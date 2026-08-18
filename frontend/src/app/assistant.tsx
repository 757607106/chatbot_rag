"use client";

import {
  AssistantRuntimeProvider,
  type RealtimeVoiceAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useEffect, useRef, useState } from "react";

import { ChatGPT } from "@/components/assistant-ui/thread";
import { chatModelAdapter } from "@/features/chat/runtime/chat-model-adapter";
import {
  isServerVoiceSupported,
  ServerVoiceAdapter,
} from "@/features/chat/runtime/server-voice-adapter";
import { commitVoiceTranscript } from "@/features/chat/runtime/voice-transcript";
import { KnowledgeNavigationLink } from "@/features/knowledge/components/knowledge-navigation-link";

export function Assistant() {
  const [voiceAdapter, setVoiceAdapter] = useState<RealtimeVoiceAdapter>();
  const [voiceUnavailableMessage, setVoiceUnavailableMessage] = useState<string>();
  const runtimeRef = useRef<ReturnType<typeof useLocalRuntime> | null>(null);

  useEffect(() => {
    setVoiceAdapter(
      new ServerVoiceAdapter({
        onError: setVoiceUnavailableMessage,
        onConversationEnd: (records) => {
          const currentRuntime = runtimeRef.current;
          if (!currentRuntime) return;
          queueMicrotask(() => {
            try {
              currentRuntime.thread.disconnectVoice();
              commitVoiceTranscript(currentRuntime.thread, records);
            } catch (error) {
              console.warn("实时语音文字记录写入失败", error);
              setVoiceUnavailableMessage("语音已结束，但文字记录保存失败。");
            }
          });
        },
      }),
    );

    if (!window.isSecureContext) {
      setVoiceUnavailableMessage("实时语音需要 HTTPS；本机调试也可使用 localhost。");
      return;
    }
    if (!isServerVoiceSupported()) {
      setVoiceUnavailableMessage("当前浏览器不支持实时语音，请使用最新版 Chrome、Edge 或 Safari。");
    }
  }, []);

  const runtime = useLocalRuntime(chatModelAdapter, {
    adapters: {
      voice: voiceAdapter,
    },
  });
  runtimeRef.current = runtime;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="h-dvh">
        <ChatGPT
          sidebarNavigation={<KnowledgeNavigationLink />}
          collapsedSidebarNavigation={<KnowledgeNavigationLink compact />}
          mobileNavigation={<KnowledgeNavigationLink />}
          voiceUnavailableMessage={voiceUnavailableMessage}
        />
      </main>
    </AssistantRuntimeProvider>
  );
}
