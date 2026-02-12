import { useMemo, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import {
    MessageSquarePlus,
    MessageSquare,
    Trash2,
    Pencil,
    Search,
    CheckSquare,
    X,
} from "lucide-react";
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
    onDeleteSessions: (ids: string[]) => void;
}

export function ChatSidebar({
    sessions,
    activeSessionId,
    onSelectSession,
    onNewChat,
    onDeleteSession,
    onRenameSession,
    onDeleteSessions,
}: ChatSidebarProps) {
    const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
    const [editTitle, setEditTitle] = useState("");
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState<Record<string, boolean>>({});
    const [searchQuery, setSearchQuery] = useState("");

    const selectedIds = useMemo(
        () => Object.entries(selected).filter(([, v]) => v).map(([k]) => k),
        [selected]
    );

    /** Filter sessions by search query (title match). */
    const filteredSessions = useMemo(() => {
        const q = searchQuery.trim().toLowerCase();
        if (!q) return sessions;
        return sessions.filter((s) =>
            (s.title || "New Chat").toLowerCase().includes(q)
        );
    }, [sessions, searchQuery]);

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

    const toggleSelectMode = () => {
        setSelectMode((prev) => {
            const next = !prev;
            if (!next) setSelected({});
            return next;
        });
        setEditingSessionId(null);
    };

    const toggleSelected = (id: string) => {
        setSelected((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    const handleDeleteSelected = () => {
        if (selectedIds.length === 0) return;
        if (!confirm(`Delete ${selectedIds.length} chat(s)? This cannot be undone.`)) return;
        onDeleteSessions(selectedIds);
        setSelected({});
        setSelectMode(false);
    };

    return (
        <div className="flex flex-col h-full bg-muted/30 w-full">
            {/* Header */}
            <div className="p-3 border-b space-y-2.5">
                <Button onClick={onNewChat} className="w-full justify-start gap-2 h-9" variant="default" size="sm">
                    <MessageSquarePlus className="h-4 w-4" />
                    New Chat
                </Button>

                {/* Search */}
                <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                    <Input
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search chats..."
                        className="pl-8 h-8 text-sm bg-background"
                    />
                    {searchQuery && (
                        <button
                            className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
                            onClick={() => setSearchQuery("")}
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    )}
                </div>

                {/* Select mode toggle */}
                {sessions.length > 0 && (
                    <div className="flex items-center gap-2">
                        <Button
                            onClick={toggleSelectMode}
                            className="flex-1 gap-1.5 h-8 text-xs"
                            variant="outline"
                            size="sm"
                        >
                            <CheckSquare className="h-3.5 w-3.5" />
                            {selectMode ? "Cancel" : "Select"}
                        </Button>
                        {selectMode && (
                            <Button
                                onClick={handleDeleteSelected}
                                className="flex-1 gap-1.5 h-8 text-xs"
                                variant="destructive"
                                size="sm"
                                disabled={selectedIds.length === 0}
                            >
                                <Trash2 className="h-3.5 w-3.5" />
                                Delete ({selectedIds.length})
                            </Button>
                        )}
                    </div>
                )}
            </div>

            {/* Session list */}
            <ScrollArea className="flex-1 px-2 py-2">
                <div className="space-y-0.5">
                    {filteredSessions.length === 0 ? (
                        <div className="text-center text-muted-foreground text-sm py-8 px-4">
                            {searchQuery
                                ? "No matching chats found."
                                : <>No recent chats.<br />Start a new conversation!</>}
                        </div>
                    ) : (
                        filteredSessions.map((session) => {
                            const isActive = activeSessionId === session.id;

                            return (
                                <div
                                    key={session.id}
                                    className={cn(
                                        "group flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm transition-all cursor-pointer",
                                        isActive
                                            ? "bg-primary/10 text-primary"
                                            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                                    )}
                                    onClick={() => {
                                        if (selectMode) {
                                            toggleSelected(session.id);
                                            return;
                                        }
                                        onSelectSession(session.id);
                                    }}
                                >
                                    {selectMode ? (
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border border-input accent-primary shrink-0"
                                            checked={Boolean(selected[session.id])}
                                            onChange={() => toggleSelected(session.id)}
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    ) : (
                                        <MessageSquare className="h-4 w-4 shrink-0 opacity-60" />
                                    )}

                                    {editingSessionId === session.id ? (
                                        <Input
                                            value={editTitle}
                                            onChange={(e) => setEditTitle(e.target.value)}
                                            onKeyDown={(e) => handleKeyDown(e, session.id)}
                                            onBlur={() => handleRename(session.id)}
                                            autoFocus
                                            className="h-6 py-0 px-1 text-xs"
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    ) : (
                                        <div
                                            className="flex-1 overflow-hidden"
                                            onDoubleClick={(e) => {
                                                e.stopPropagation();
                                                startEditing(session);
                                            }}
                                        >
                                            <p className="truncate leading-none mb-1 text-foreground/90 text-[13px]">
                                                {session.title || "New Chat"}
                                            </p>
                                            <div className="flex items-center gap-2">
                                                <span className="text-[10px] text-muted-foreground">
                                                    {formatDistanceToNow(new Date(session.last_activity), { addSuffix: true })}
                                                </span>
                                                {session.message_count > 0 && (
                                                    <span className="text-[10px] text-muted-foreground">
                                                        · {session.message_count} msg{session.message_count !== 1 ? "s" : ""}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Per-item actions — visible on hover (desktop) or always (touch) */}
                                    {!selectMode && (
                                        <div className="flex gap-0.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity shrink-0">
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="h-6 w-6 hover:bg-background/50"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    startEditing(session);
                                                }}
                                                title="Rename"
                                            >
                                                <Pencil className="h-3 w-3" />
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="h-6 w-6 hover:bg-destructive/10 hover:text-destructive"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onDeleteSession(e, session.id);
                                                }}
                                                title="Delete"
                                            >
                                                <Trash2 className="h-3 w-3" />
                                            </Button>
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            </ScrollArea>
        </div>
    );
}
