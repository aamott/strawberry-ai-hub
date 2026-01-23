import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import { Loader2 } from "lucide-react";

interface Message {
    id: number | string;
    role: string;
    content: string;
}

interface MessageListProps {
    messages: Message[];
    isLoading?: boolean;
}

const styles = {
    emptyStateContainer: "flex flex-col items-center justify-center h-full text-center p-8 text-muted-foreground",
    emptyStateIconWrapper: "h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-4",
    emptyStateIcon: "text-2xl",
    emptyStateTitle: "text-lg font-medium text-foreground",
    emptyStateDescription: "max-w-sm mt-2",
    listContainer: "flex-1 overflow-y-auto p-4 space-y-6",
    loadingContainer: "flex justify-start",
    loadingWrapper: "flex items-center gap-2 text-muted-foreground text-sm pl-12",
    loadingIcon: "h-4 w-4 animate-spin",
    bottomSpacer: "h-1"
};

export function MessageList({ messages, isLoading }: MessageListProps) {
    const bottomRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, isLoading]);

    if (messages.length === 0 && !isLoading) {
        return (
            <div className={styles.emptyStateContainer}>
                <div className={styles.emptyStateIconWrapper}>
                    <span className={styles.emptyStateIcon}>🍓</span>
                </div>
                <h3 className={styles.emptyStateTitle}>Welcome to Strawberry AI</h3>
                <p className={styles.emptyStateDescription}>Start a conversation to chat with your local AI models.</p>
            </div>
        );
    }

    return (
        <div className={styles.listContainer}>
            {messages.map((msg) => (
                <MessageBubble
                    key={msg.id}
                    role={msg.role}
                    content={msg.content}
                />
            ))}

            {isLoading && (
                <div className={styles.loadingContainer}>
                    <div className={styles.loadingWrapper}>
                        <Loader2 className={styles.loadingIcon} />
                        <span>Thinking...</span>
                    </div>
                </div>
            )}

            <div ref={bottomRef} className={styles.bottomSpacer} />
        </div>
    );
}
