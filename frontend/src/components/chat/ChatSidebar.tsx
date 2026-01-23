import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { MessageSquarePlus, MessageSquare, Trash2, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";

interface Session {
    id: string;
    title?: string;
    last_activity: string;
    message_count: number;
}

interface ChatSidebarProps {
    sessions: Session[];
    activeSessionId?: string;
    onSelectSession: (id: string) => void;
    onNewChat: () => void;
    onDeleteSession: (e: React.MouseEvent, id: string) => void;
    onRenameSession: (id: string, newTitle: string) => void;
}

const styles = {
    container: "flex flex-col h-full border-r bg-muted/30 w-full md:w-80",
    header: "p-4 border-b space-y-4",
    newChatButton: "w-full justify-start gap-2 h-10 shadow-sm",
    scrollArea: "flex-1 px-2 py-2",
    listContainer: "space-y-1",
    emptyState: "text-center text-muted-foreground text-sm py-8 px-4",
    sessionItem: (isActive: boolean) => cn(
        "group flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-all hover:bg-accent cursor-pointer",
        isActive ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground"
    ),
    sessionIcon: "h-4 w-4 shrink-0 opacity-70",
    editInput: "h-6 py-0 px-1 text-xs",
    sessionInfo: "flex-1 overflow-hidden",
    sessionTitle: "truncate leading-none mb-1 text-foreground/90",
    sessionTime: "text-[10px] text-muted-foreground",
    actionButtons: "flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity",
    actionButton: "h-6 w-6 hover:bg-background/50",
    deleteButton: "h-6 w-6 hover:bg-destructive/10 hover:text-destructive"
};

export function ChatSidebar({
    sessions,
    activeSessionId,
    onSelectSession,
    onNewChat,
    onDeleteSession,
    onRenameSession
}: ChatSidebarProps) {
    const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
    const [editTitle, setEditTitle] = useState("");

    const startEditing = (session: Session) => {
        setEditingSessionId(session.id);
        setEditTitle(session.title || "New Chat");
    };

    const handleRename = async (sessionId: string) => {
        if (editTitle.trim()) {
            onRenameSession(sessionId, editTitle.trim());
        }
        setEditingSessionId(null);
    };

    const handleKeyDown = (e: React.KeyboardEvent, sessionId: string) => {
        if (e.key === "Enter") {
            handleRename(sessionId);
        } else if (e.key === "Escape") {
            setEditingSessionId(null);
        }
    };
    return (
        <div className={styles.container}>
            <div className={styles.header}>
                <Button onClick={onNewChat} className={styles.newChatButton} variant="default">
                    <MessageSquarePlus className="h-4 w-4" />
                    New Chat
                </Button>
                {/* <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input placeholder="Search chats..." className="pl-9 h-9 bg-background" />
                </div> */}
            </div>

            <ScrollArea className={styles.scrollArea}>
                <div className={styles.listContainer}>
                    {sessions.length === 0 ? (
                        <div className={styles.emptyState}>
                            No recent chats.
                            <br />Start a new conversation!
                        </div>
                    ) : (
                        sessions.map((session) => (
                            <div
                                key={session.id}
                                className={styles.sessionItem(activeSessionId === session.id)}
                                onClick={() => onSelectSession(session.id)}
                            >
                                <MessageSquare className={styles.sessionIcon} />

                                {editingSessionId === session.id ? (
                                    <Input
                                        value={editTitle}
                                        onChange={(e) => setEditTitle(e.target.value)}
                                        onKeyDown={(e) => handleKeyDown(e, session.id)}
                                        onBlur={() => handleRename(session.id)}
                                        autoFocus
                                        className={styles.editInput}
                                        onClick={(e) => e.stopPropagation()}
                                    />
                                ) : (
                                    <div className={styles.sessionInfo} onDoubleClick={(e) => {
                                        e.stopPropagation();
                                        startEditing(session);
                                    }}>
                                        <p className={styles.sessionTitle}>
                                            {session.title || "New Chat"}
                                        </p>
                                        <span className={styles.sessionTime}>
                                            {formatDistanceToNow(new Date(session.last_activity), { addSuffix: true })}
                                        </span>
                                    </div>
                                )}

                                <div className={styles.actionButtons}>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className={styles.actionButton}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            startEditing(session);
                                        }}
                                    >
                                        <Pencil className="h-3 w-3" />
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className={styles.deleteButton}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onDeleteSession(e, session.id);
                                        }}
                                    >
                                        <Trash2 className="h-3 w-3" />
                                    </Button>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </ScrollArea>
        </div>
    );
}
