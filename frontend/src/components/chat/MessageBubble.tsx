import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Copy, Bot, User, Wrench, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MessageBubbleProps {
    role: string;
    content: string;
    isStreaming?: boolean;
}

const styles = {
    container: (isUser: boolean) => cn(
        "flex w-full mb-4",
        isUser ? "justify-end" : "justify-start"
    ),
    bubbleWrapper: (isUser: boolean) => cn(
        "flex max-w-[85%] md:max-w-[80%] gap-2",
        isUser ? "flex-row-reverse" : "flex-row"
    ),
    avatar: (isUser: boolean) => cn(
        "h-8 w-8 rounded-full flex items-center justify-center shrink-0",
        isUser ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
    ),
    messageContent: (isUser: boolean) => cn(
        "group relative rounded-2xl px-4 py-3 text-sm shadow-xs min-w-0 overflow-hidden",
        isUser
            ? "bg-primary text-primary-foreground rounded-tr-none"
            : "bg-muted/50 text-foreground border rounded-tl-none"
    ),
    prose: "prose prose-sm dark:prose-invert max-w-none break-words",
    codeBlockWrapper: "relative rounded-md bg-muted p-2 my-2 font-mono text-xs overflow-x-auto max-w-full",
    inlineCode: "bg-muted px-1.5 py-0.5 rounded text-xs",
    actionContainer: "absolute -bottom-8 right-0 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1",
    actionButton: "h-6 w-6"
};

export function MessageBubble({ role, content }: MessageBubbleProps) {
    const isUser = role === "user";
    const isTool = role === "tool";

    const copyToClipboard = () => {
        navigator.clipboard.writeText(content);
    };

    const downloadSnippet = () => {
        const blob = new Blob([content], { type: "text/markdown" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `message-${Date.now()}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    return (
        <div className={styles.container(isUser)}>
            <div className={styles.bubbleWrapper(isUser)}>
                {/* Avatar */}
                <div className={styles.avatar(isUser)}>
                    {isUser ? (
                        <User className="h-5 w-5" />
                    ) : isTool ? (
                        <Wrench className="h-5 w-5" />
                    ) : (
                        <Bot className="h-5 w-5" />
                    )}
                </div>

                {/* Message Content */}
                <div
                    className={cn(
                        styles.messageContent(isUser),
                        isTool && "bg-muted/30 border border-dashed"
                    )}
                >
                    {/* Markdown Content */}
                    <div className={styles.prose}>
                        <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                                code({
                                    inline,
                                    className,
                                    children,
                                    ...props
                                }: ComponentProps<"code"> & { inline?: boolean }) {
                                    return !inline ? (
                                        <div className={styles.codeBlockWrapper}>
                                            <code {...props} className={className}>
                                                {children}
                                            </code>
                                        </div>
                                    ) : (
                                        <code {...props} className={cn(styles.inlineCode, className)}>
                                            {children}
                                        </code>
                                    )
                                }
                            }}
                        >
                            {content}
                        </ReactMarkdown>
                    </div>

                    {/* Hover Actions */}
                    <div className={styles.actionContainer}>
                        <Button
                            variant="ghost"
                            size="icon"
                            className={styles.actionButton}
                            onClick={copyToClipboard}
                            title="Copy message"
                        >
                            <Copy className="h-3 w-3" />
                        </Button>
                        <Button
                            variant="ghost"
                            size="icon"
                            className={styles.actionButton}
                            onClick={downloadSnippet}
                            title="Download message"
                        >
                            <Download className="h-3 w-3" />
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}
