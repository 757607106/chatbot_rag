"use client";

import {
  AssistantRuntimeProvider,
  type DictationAdapter,
  type RealtimeVoiceAdapter,
  useLocalRuntime,
} from "@assistant-ui/react";
import { useEffect, useState } from "react";

import { ChatGPT } from "@/components/assistant-ui/thread";
import { chatModelAdapter } from "@/features/chat/runtime/chat-model-adapter";
import {
  isServerDictationSupported,
  ServerDictationAdapter,
} from "@/features/chat/runtime/server-dictation-adapter";
import {
  isServerVoiceSupported,
  ServerVoiceAdapter,
} from "@/features/chat/runtime/server-voice-adapter";
import { KnowledgeNavigationLink } from "@/features/knowledge/components/knowledge-navigation-link";

export function Assistant() {
  const [dictationAdapter, setDictationAdapter] = useState<DictationAdapter>();
  const [voiceAdapter, setVoiceAdapter] = useState<RealtimeVoiceAdapter>();
  const [dictationUnavailableMessage, setDictationUnavailableMessage] = useState<string>();

  useEffect(() => {
    setDictationAdapter(
      new ServerDictationAdapter({
        onStart: () => setDictationUnavailableMessage(undefined),
        onError: setDictationUnavailableMessage,
      }),
    );
    setVoiceAdapter(
      new ServerVoiceAdapter({
        onError: setDictationUnavailableMessage,
      }),
    );

    if (!window.isSecureContext) {
      setDictationUnavailableMessage(
        "语音输入需要 HTTPS；在运行服务的本机调试时也可使用 localhost。",
      );
      return;
    }
    if (!isServerDictationSupported()) {
      setDictationUnavailableMessage("当前浏览器不支持录音，请使用最新版 Chrome、Edge 或 Safari。");
      return;
    }
    if (!isServerVoiceSupported()) {
      setDictationUnavailableMessage(
        "当前浏览器不支持语音模式，请使用最新版 Chrome、Edge 或 Safari。",
      );
    }
  }, []);

  const runtime = useLocalRuntime(chatModelAdapter, {
    adapters: {
      dictation: dictationAdapter,
      voice: voiceAdapter,
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="h-dvh">
        <ChatGPT
          sidebarNavigation={<KnowledgeNavigationLink />}
          collapsedSidebarNavigation={<KnowledgeNavigationLink compact />}
          mobileNavigation={<KnowledgeNavigationLink />}
          dictationUnavailableMessage={dictationUnavailableMessage}
        />
      </main>
    </AssistantRuntimeProvider>
  );
}
