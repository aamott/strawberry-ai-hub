import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { ChatArea } from "@/components/chat/ChatArea";
import { useToast } from "@/components/ui/use-toast";
import { useChatSessions } from "@/contexts/ChatSessionContext";
import { streamHubChatCompletion, type HubChatMessage } from "@/lib/chatStream";

interface Message {
    id: number | string;
    role: string;
    content: string;
    /**
     * If false, the message is UI-only and should not be sent back as model context.
     * We use this for "tool_call_started" lines (they are informative but not tool output).
     */
    context?: boolean;
}

function toolArgsPreview(args: Record<string, unknown>): string {
    const entries = Object.entries(args);
    if (entries.length === 0) return "";
    return entries
        .slice(0, 2)
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(", ");
}

function formatToolCallStarted(toolName: string, args: Record<string, unknown>): string {
    if (toolName === "python_exec" && typeof args.code === "string") {
        const code = String(args.code || "");
        if (code.includes("\n")) {
            return `* ${toolName}(code=)\n\n\`\`\`python\n${code}\n\`\`\`\n\n...`;
        }
        return `* ${toolName}(code=${code}) ...`;
    }
    const preview = toolArgsPreview(args);
    return `* ${toolName}(${preview}) ...`;
}

function formatToolCallResult(
    toolName: string,
    success: boolean,
    result?: string | null,
    error?: string | null,
    cached?: boolean
): { ui: string; persist: string } {
    const status = success ? "✓" : "✗";
    const output = success ? (result ?? "") : (error ?? "");
    const cachedNote = cached ? " (cached)" : "";

    const ui = `* ${toolName} ${status}${cachedNote}\n\n\`\`\`text\n${output}\n\`\`\``;
    const persist = [
        `tool_name=${toolName}`,
        `success=${success}`,
        `cached=${Boolean(cached)}`,
        "",
        output,
    ].join("\n");
    return { ui, persist };
}

/**
 * Chat page — consumes session state from ChatSessionContext (owned by Dashboard).
 * Only manages messages and streaming locally.
 */
export function Chat() {
    const {
        activeSessionId,
        createSession,
        fetchSessions,
    } = useChatSessions();

    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const { toast } = useToast();

    const fetchMessages = useCallback(async (sessionId: string) => {
        try {
            const res = await api.get(`/sessions/${sessionId}/messages`);
            setMessages(res.data.messages);
        } catch (error) {
            console.error("Failed to fetch messages", error);
            toast({
                title: "Error",
                description: "Failed to load chat history.",
                variant: "destructive",
            });
        }
    }, [toast]);

    // Load messages when active session changes.
    useEffect(() => {
        if (activeSessionId) {
            fetchMessages(activeSessionId);
        } else {
            setMessages([]);
        }
    }, [activeSessionId, fetchMessages]);

    const handleSendMessage = async (content: string) => {
        if (isLoading) return;
        setIsLoading(true);

        let currentSessionId = activeSessionId;

        // Create session if none exists.
        if (!currentSessionId) {
            const newId = await createSession();
            if (!newId) {
                toast({
                    title: "Error",
                    description: "Failed to start new chat.",
                    variant: "destructive",
                });
                setIsLoading(false);
                return;
            }
            currentSessionId = newId;
        }

        // Optimistic UI update.
        const tempUserMsg: Message = { id: Date.now(), role: "user", content };
        setMessages(prev => [...prev, tempUserMsg]);

        try {
            // 1. Save user message
            await api.post(`/sessions/${currentSessionId}/messages`, { role: "user", content });

            // 2. Stream tool calls/results and the final assistant message.
            const history: HubChatMessage[] = [...messages, { id: "ctx-user", role: "user", content }]
                .filter(m => m.context !== false)
                .map((m) => ({
                    role: m.role as HubChatMessage["role"],
                    content: m.content,
                }));

            let finalAssistant: string | null = null;

            for await (const event of streamHubChatCompletion({
                model: "gpt-4o-mini",
                messages: history,
                enable_tools: true,
            })) {
                if (event.type === "tool_call_started") {
                    setMessages((prev) => [
                        ...prev,
                        {
                            id: `tool-start-${Date.now()}-${Math.random()}`,
                            role: "tool",
                            content: formatToolCallStarted(
                                event.tool_name,
                                (event.arguments ?? {}) as Record<string, unknown>
                            ),
                            context: false,
                        },
                    ]);
                }

                if (event.type === "tool_call_result") {
                    const { ui, persist } = formatToolCallResult(
                        event.tool_name,
                        event.success,
                        event.result,
                        event.error,
                        event.cached
                    );

                    setMessages((prev) => [
                        ...prev,
                        {
                            id: `tool-result-${Date.now()}-${Math.random()}`,
                            role: "tool",
                            content: ui,
                        },
                    ]);

                    // Persist tool results (but not "started" events) so future turns
                    // can include tool outputs as context.
                    await api.post(`/sessions/${currentSessionId}/messages`, {
                        role: "tool",
                        content: persist,
                    });
                }

                if (event.type === "assistant_message") {
                    finalAssistant = event.content ?? "";
                    setMessages((prev) => [
                        ...prev,
                        {
                            id: `assistant-${Date.now()}-${Math.random()}`,
                            role: "assistant",
                            content: finalAssistant || "(empty response)",
                        },
                    ]);
                }

                if (event.type === "error") {
                    throw new Error(event.error);
                }

                if (event.type === "done") {
                    break;
                }
            }

            if (finalAssistant !== null) {
                await api.post(`/sessions/${currentSessionId}/messages`, {
                    role: "assistant",
                    content: finalAssistant,
                });
            }

            await fetchSessions(); // Update last_activity + message_count

        } catch (error) {
            console.error(error);
            toast({
                title: "Error",
                description: "Failed to send message.",
                variant: "destructive",
            });
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex h-full overflow-hidden bg-background">
            <div className="flex-1 flex flex-col min-w-0 h-full">
                <ChatArea
                    messages={messages}
                    onSend={handleSendMessage}
                    isLoading={isLoading}
                />
            </div>
        </div>
    );
}
