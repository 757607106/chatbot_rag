const DEFAULT_CHATBOT_API_URL = "http://127.0.0.1:8000/api/v1/chat/stream";

export function getChatUpstreamUrl(): string {
  return process.env.CHATBOT_API_URL ?? DEFAULT_CHATBOT_API_URL;
}

export function getMediaUpstreamUrl(assetId: string): string {
  return new URL(`../media/${assetId}`, getChatUpstreamUrl()).toString();
}

export function getKnowledgeUpstreamUrl(pathname: string): string {
  const root = new URL("../knowledge/", getChatUpstreamUrl());
  return new URL(pathname, root).toString();
}
