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

export function MessageList({ messages, isLoading }: MessageListProps) {
    const bottomRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, isLoading]);

    if (messages.length === 0 && !isLoading) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-center p-8 text-muted-foreground">
                <div className="h-12 w-12 rounded-full bg-muted flex items-center justify-center mb-4">
                    <span className="text-2xl">🍓</span>
                </div>
                <h3 className="text-lg font-medium text-foreground">Welcome to Strawberry AI</h3>
                <p className="max-w-sm mt-2">Start a conversation to chat with your local AI models.</p>
            </div>
        );
    }

    return (
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
            {messages.map((msg) => (
                <MessageBubble
                    key={msg.id}
                    role={msg.role}
                    content={msg.content}
                />
            ))}

            {isLoading && (
                <div className="flex justify-start">
                    <div className="flex items-center gap-2 text-muted-foreground text-sm pl-12">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>Thinking...</span>
                    </div>
                </div>
            )}

            <div ref={bottomRef} className="h-1" />
        </div>
    );
}
