import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { ChatArea } from "@/components/chat/ChatArea";
import { useToast } from "@/components/ui/use-toast";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Menu } from "lucide-react";
import { streamHubChatCompletion, type HubChatMessage } from "@/lib/chatStream";

interface Session {
    id: string;
    title?: string;
    last_activity: string;
    message_count: number;
}

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

const styles = {
    container: "flex h-full overflow-hidden bg-background",
    sidebarDesktop: "hidden md:block h-full",
    mobileHeader: "md:hidden flex items-center p-3 border-b bg-background/95 backdrop-blur z-10",
    mobileMenuButton: "mr-2",
    mobileMenuIcon: "h-5 w-5",
    mobileTitle: "font-semibold text-lg",
    sheetContent: "p-0 w-80",
    mainArea: "flex-1 flex flex-col min-w-0 h-full"
};

export function Chat() {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [activeSessionId, setActiveSessionId] = useState<string | undefined>();
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const { toast } = useToast();

    const fetchSessions = useCallback(async () => {
        try {
            const res = await api.get("/sessions");
            setSessions(res.data.sessions);
        } catch (error) {
            console.error("Failed to fetch sessions", error);
        }
    }, []);

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

    useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    useEffect(() => {
        if (activeSessionId) {
            fetchMessages(activeSessionId);
        } else {
            setMessages([]);
        }
    }, [activeSessionId, fetchMessages]);

    const handleNewChat = useCallback(async () => {
        try {
            const res = await api.post("/sessions", {});
            const newSession = res.data;
            setSessions((prev) => [newSession, ...prev]);
            setActiveSessionId(newSession.id);
            setSidebarOpen(false); // Close mobile sidebar on selection
        } catch (error) {
            console.error("Failed to create new chat", error);
            toast({
                title: "Error",
                description: "Failed to create new chat.",
                variant: "destructive",
            });
        }
    }, [toast]);

    const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
        e.stopPropagation();
        if (!confirm("Are you sure you want to delete this chat?")) return;

        try {
            await api.delete(`/sessions/${sessionId}`);
            setSessions((prev) => prev.filter(s => s.id !== sessionId));
            if (activeSessionId === sessionId) {
                setActiveSessionId(undefined);
            }
            toast({ title: "Chat deleted" });
        } catch (error) {
            console.error("Failed to delete chat", error);
            toast({
                title: "Error",
                description: "Failed to delete chat.",
                variant: "destructive",
            });
        }
    };

    const handleDeleteSessions = useCallback(async (ids: string[]) => {
        try {
            // Delete sequentially to avoid spiking the backend.
            for (const id of ids) {
                await api.delete(`/sessions/${id}`);
            }

            toast({ title: "Chats deleted", description: `Deleted ${ids.length} chat(s).` });

            // Refresh session list and clear active chat if it was deleted.
            await fetchSessions();
            if (activeSessionId && ids.includes(activeSessionId)) {
                setActiveSessionId(undefined);
                setMessages([]);
            }
        } catch (error) {
            console.error("Failed deleting chats", error);
            toast({
                title: "Error",
                description: "Failed to delete chats.",
                variant: "destructive",
            });
        }
    }, [activeSessionId, fetchSessions, toast]);

    const handleSendMessage = async (content: string) => {
        if (isLoading) return;
        setIsLoading(true);

        let currentSessionId = activeSessionId;

        // Create session if none exists
        if (!currentSessionId) {
            try {
                const res = await api.post("/sessions", {});
                const newSession = res.data;
                setSessions((prev) => [newSession, ...prev]);
                setActiveSessionId(newSession.id);
                currentSessionId = newSession.id;
            } catch (error) {
                console.error("Failed to start new chat", error);
                toast({
                    title: "Error",
                    description: "Failed to start new chat.",
                    variant: "destructive",
                });
                setIsLoading(false);
                return;
            }
        }

        // Optimistic UI update
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
            // Note: we intentionally avoid re-fetching messages here so that
            // in-flight tool-call "started" lines remain visible.

        } catch (error) {
            console.error(error);
            toast({
                title: "Error",
                description: "Failed to send message.",
                variant: "destructive",
            });
            // Remove optimistic message on critical failure? Or just leave it with error state?
            // For now, simple implementation.
        } finally {
            setIsLoading(false);
        }
    };

    const handleRenameSession = async (sessionId: string, newTitle: string) => {
        try {
            await api.patch(`/sessions/${sessionId}`, { title: newTitle });
            setSessions((prev) =>
                prev.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s))
            );
        } catch (error) {
            console.error("Failed to rename chat", error);
            toast({
                title: "Error",
                description: "Failed to rename chat.",
                variant: "destructive",
            });
        }
    };

    return (
        <div className={styles.container}>
            {/* Desktop Sidebar */}
            <div className={styles.sidebarDesktop}>
                <ChatSidebar
                    sessions={sessions}
                    activeSessionId={activeSessionId}
                    onSelectSession={setActiveSessionId}
                    onNewChat={handleNewChat}
                    onDeleteSession={handleDeleteSession}
                    onRenameSession={handleRenameSession}
                    onDeleteSessions={handleDeleteSessions}
                />
            </div>

            {/* Main Chat Area */}
            <div className={styles.mainArea}>
                {/* Mobile Header */}
                <div className={styles.mobileHeader}>
                    <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
                        <SheetTrigger asChild>
                            <Button variant="ghost" size="icon" className={styles.mobileMenuButton}>
                                <Menu className={styles.mobileMenuIcon} />
                            </Button>
                        </SheetTrigger>
                        <SheetContent side="left" className={styles.sheetContent}>
                            <ChatSidebar
                                sessions={sessions}
                                activeSessionId={activeSessionId}
                                onSelectSession={(id) => {
                                    setActiveSessionId(id);
                                    setSidebarOpen(false);
                                }}
                                onNewChat={handleNewChat}
                                onDeleteSession={handleDeleteSession}
                                onRenameSession={handleRenameSession}
                                onDeleteSessions={handleDeleteSessions}
                            />
                        </SheetContent>
                    </Sheet>
                    <span className={styles.mobileTitle}>Strawberry AI</span>
                </div>

                <ChatArea
                    messages={messages}
                    onSend={handleSendMessage}
                    isLoading={isLoading}
                />
            </div>
        </div>
    );
}
