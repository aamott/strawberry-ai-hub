import { parseSseDataFrames } from "@/lib/sse";

export type HubChatStreamEvent =
  | {
      type: "tool_call_started";
      tool_call_id?: string;
      tool_name: string;
      arguments: Record<string, unknown>;
    }
  | {
      type: "tool_call_result";
      tool_call_id?: string;
      tool_name: string;
      success: boolean;
      result?: string | null;
      error?: string | null;
      cached?: boolean;
    }
  | {
      type: "assistant_message";
      content: string;
      model?: string;
      usage?: Record<string, unknown>;
    }
  | { type: "error"; error: string }
  | { type: "done" };

export interface HubChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}

export interface HubChatStreamParams {
  messages: HubChatMessage[];
  enable_tools: boolean;
  model?: string;
}

function getAuthHeader(): string | undefined {
  const token = localStorage.getItem("admin_token");
  return token ? `Bearer ${token}` : undefined;
}

export async function* streamHubChatCompletion(
  params: HubChatStreamParams,
): AsyncGenerator<HubChatStreamEvent> {
  const auth = getAuthHeader();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (auth) headers.Authorization = auth;

  const res = await fetch("/api/v1/chat/completions", {
    method: "POST",
    headers,
    body: JSON.stringify({
      model: params.model ?? "gpt-4o-mini",
      messages: params.messages,
      enable_tools: params.enable_tools,
      stream: true,
    }),
  });

  if (!res.ok) {
    const errorText = await res.text().catch(() => "");
    throw new Error(
      `Chat request failed (${res.status}): ${errorText || res.statusText}`,
    );
  }

  for await (const data of parseSseDataFrames(res)) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      yield { type: "error", error: `Invalid SSE JSON payload: ${data}` };
      continue;
    }

    if (!parsed || typeof parsed !== "object" || !("type" in parsed)) {
      yield { type: "error", error: "Invalid SSE event shape." };
      continue;
    }

    yield parsed as HubChatStreamEvent;
  }
}

