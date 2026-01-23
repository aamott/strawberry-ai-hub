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

const styles = {
    container: "flex flex-col flex-1 min-h-0 bg-background relative",
    inputWrapper: "px-4 pb-4 max-w-4xl w-full mx-auto"
};

export function ChatArea({ messages, onSend, isLoading }: ChatAreaProps) {
    return (
        <div className={styles.container}>
            <MessageList messages={messages} isLoading={isLoading} />
            <div className={styles.inputWrapper}>
                <ChatInput onSend={onSend} isLoading={isLoading} />
            </div>
        </div>
    );
}
