import React from "react";
import { formatDistanceToNow } from "date-fns";
import { MessageSquarePlus, MessageSquare, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

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
}

export function ChatSidebar({
    sessions,
    activeSessionId,
    onSelectSession,
    onNewChat,
    onDeleteSession
}: ChatSidebarProps) {
    return (
        <div className="flex flex-col h-full border-r bg-muted/30 w-full md:w-80">
            <div className="p-4 border-b space-y-4">
                <Button onClick={onNewChat} className="w-full justify-start gap-2 h-10 shadow-sm" variant="default">
                    <MessageSquarePlus className="h-4 w-4" />
                    New Chat
                </Button>
                {/* <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input placeholder="Search chats..." className="pl-9 h-9 bg-background" />
                </div> */}
            </div>

            <ScrollArea className="flex-1 px-2 py-2">
                <div className="space-y-1">
                    {sessions.length === 0 ? (
                        <div className="text-center text-muted-foreground text-sm py-8 px-4">
                            No recent chats.
                            <br />Start a new conversation!
                        </div>
                    ) : (
                        sessions.map((session) => (
                            <div
                                key={session.id}
                                className={cn(
                                    "group flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-all hover:bg-accent cursor-pointer",
                                    activeSessionId === session.id ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground"
                                )}
                                onClick={() => onSelectSession(session.id)}
                            >
                                <MessageSquare className="h-4 w-4 shrink-0 opacity-70" />
                                <div className="flex-1 overflow-hidden">
                                    <p className="truncate leading-none mb-1 text-foreground/90">
                                        {session.title || "New Chat"}
                                    </p>
                                    <span className="text-[10px] text-muted-foreground">
                                        {formatDistanceToNow(new Date(session.last_activity), { addSuffix: true })}
                                    </span>
                                </div>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive/10 hover:text-destructive"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onDeleteSession(e, session.id);
                                    }}
                                >
                                    <Trash2 className="h-3 w-3" />
                                </Button>
                            </div>
                        ))
                    )}
                </div>
            </ScrollArea>
        </div>
    );
}
