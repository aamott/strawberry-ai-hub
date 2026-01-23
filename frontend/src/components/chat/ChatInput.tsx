import { useState, useRef, useEffect, type KeyboardEvent } from "react";
import { SendHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea"

interface ChatInputProps {
    onSend: (message: string) => void;
    isLoading?: boolean;
}

const styles = {
    container: "border-t bg-background/95 backdrop-blur p-3 md:p-4",
    inputWrapper: "relative flex items-end gap-2 max-w-4xl mx-auto dark:bg-muted/30 p-2 rounded-xl ring-1 ring-border focus-within:ring-ring transition-all",
    textarea: "min-h-[24px] max-h-[200px] w-full resize-none border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 px-3 py-2",
    sendButton: "h-8 w-8 mb-1 rounded-lg shrink-0",
    disclaimerContainer: "text-center mt-2",
    disclaimerText: "text-[10px] text-muted-foreground"
};

export function ChatInput({ onSend, isLoading }: ChatInputProps) {
    const [input, setInput] = useState("");
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    const handleSend = () => {
        if (!input.trim() || isLoading) return;
        onSend(input);
        setInput("");
        // Reset height
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
        }
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    // Auto-resize textarea
    useEffect(() => {
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = "auto";
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    }, [input]);

    return (
        <div className={styles.container}>
            <div className={styles.inputWrapper}>
                <Textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Message Strawberry AI..."
                    className={styles.textarea}
                    rows={1}
                />
                <Button
                    size="icon"
                    onClick={handleSend}
                    disabled={!input.trim() || isLoading}
                    className={styles.sendButton}
                >
                    <SendHorizontal className="h-4 w-4" />
                </Button>
            </div>
            <div className={styles.disclaimerContainer}>
                <p className={styles.disclaimerText}>AI can make mistakes. Check important info.</p>
            </div>
        </div>
    );
}
