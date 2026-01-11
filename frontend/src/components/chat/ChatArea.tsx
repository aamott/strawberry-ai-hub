import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";

interface Message {
    id: number | string;
    role: string;
    content: string;
}

interface ChatAreaProps {
    messages: Message[];
    onSend: (message: string) => void;
    isLoading: boolean;
}

export function ChatArea({ messages, onSend, isLoading }: ChatAreaProps) {
    return (
        <div className="flex flex-col h-full bg-background relative">
            <MessageList messages={messages} isLoading={isLoading} />
            <div className="px-4 pb-4 max-w-4xl w-full mx-auto">
                <ChatInput onSend={onSend} isLoading={isLoading} />
            </div>
        </div>
    );
}
