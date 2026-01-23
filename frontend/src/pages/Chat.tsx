import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { ChatArea } from "@/components/chat/ChatArea";
import { useToast } from "@/components/ui/use-toast";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Menu } from "lucide-react";

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
            setSessions([newSession, ...sessions]);
            setActiveSessionId(newSession.id);
            setSidebarOpen(false); // Close mobile sidebar on selection
        } catch (error) {
            toast({
                title: "Error",
                description: "Failed to create new chat.",
                variant: "destructive",
            });
        }
    }, [sessions, toast]);

    const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
        e.stopPropagation();
        if (!confirm("Are you sure you want to delete this chat?")) return;

        try {
            await api.delete(`/sessions/${sessionId}`);
            setSessions(sessions.filter(s => s.id !== sessionId));
            if (activeSessionId === sessionId) {
                setActiveSessionId(undefined);
            }
            toast({ title: "Chat deleted" });
        } catch (error) {
            toast({
                title: "Error",
                description: "Failed to delete chat.",
                variant: "destructive",
            });
        }
    };

    const handleSendMessage = async (content: string) => {
        if (isLoading) return;
        setIsLoading(true);

        let currentSessionId = activeSessionId;

        // Create session if none exists
        if (!currentSessionId) {
            try {
                const res = await api.post("/sessions", {});
                const newSession = res.data;
                setSessions([newSession, ...sessions]);
                setActiveSessionId(newSession.id);
                currentSessionId = newSession.id;
            } catch (error) {
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
        const tempUserMsg = { id: Date.now(), role: "user", content };
        setMessages(prev => [...prev, tempUserMsg]);

        try {
            // 1. Save user message
            await api.post(`/sessions/${currentSessionId}/messages`, { role: "user", content });

            // 2. Get AI Response
            // The backend endpoint is /api/v1/chat/completions
            // We need to send the history conformant to OpenAI API if we want context,
            // but the current backend implementation of `_call_tensorzero` seems to handle single request?
            // Wait, standard /chat/completions is stateless. 
            // The backend `sessions.py` stores messages but `chat.py` doesn't seem to read from DB.
            // I need to send history manually or check if backend handles it.
            // Looking at `chat.py`, it takes `messages`. So I must send history.

            const history = messages.map(m => ({ role: m.role, content: m.content }));
            history.push({ role: "user", content });

            const aiRes = await api.post("/v1/chat/completions", {
                model: "gpt-4o", // or whatever default
                messages: history,
                enable_tools: true,
            });

            const aiContent = aiRes.data.choices[0].message.content;

            // 3. Save Assistant Message
            await api.post(`/sessions/${currentSessionId}/messages`, { role: "assistant", content: aiContent });

            // Refresh messages to get real IDs and ensure sync
            await fetchMessages(currentSessionId!);
            await fetchSessions(); // To update last_activity and snippet

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
            setSessions(sessions.map(s =>
                s.id === sessionId ? { ...s, title: newTitle } : s
            ));
        } catch (error) {
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
