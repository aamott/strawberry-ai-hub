import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { ToolModeToggle } from "./ToolModeToggle";

interface Message {
    id: number | string;
    role: string;
    content: string;
}

interface ChatAreaProps {
    messages: Message[];
    onSend: (message: string) => void;
    isLoading: boolean;
    toolMode: string;
    onToolModeChange: (mode: string) => void;
    /** True when the session has been used (mode is locked). */
    modeLocked: boolean;
}

const styles = {
    container: "flex flex-col flex-1 min-h-0 bg-background relative",
    inputWrapper: "px-4 pb-4 max-w-4xl w-full mx-auto",
};

export function ChatArea({
    messages,
    onSend,
    isLoading,
    toolMode,
    onToolModeChange,
    modeLocked,
}: ChatAreaProps) {
    return (
        <div className={styles.container}>
            <MessageList messages={messages} isLoading={isLoading} />
            <div className={styles.inputWrapper}>
                <ToolModeToggle
                    mode={toolMode}
                    onChange={onToolModeChange}
                    locked={modeLocked}
                />
                <ChatInput onSend={onSend} isLoading={isLoading} />
            </div>
        </div>
    );
}
