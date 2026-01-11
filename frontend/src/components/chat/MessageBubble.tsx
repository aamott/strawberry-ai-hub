import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { Copy, Bot, User } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MessageBubbleProps {
    role: string;
    content: string;
    isStreaming?: boolean;
}

export function MessageBubble({ role, content }: MessageBubbleProps) {
    const isUser = role === "user";

    const copyToClipboard = () => {
        navigator.clipboard.writeText(content);
    };

    return (
        <div className={cn("flex w-full", isUser ? "justify-end" : "justify-start")}>
            <div className={cn("flex max-w-[80%] gap-2", isUser ? "flex-row-reverse" : "flex-row")}>
                {/* Avatar */}
                <div className={cn(
                    "h-8 w-8 rounded-full flex items-center justify-center shrink-0",
                    isUser ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                )}>
                    {isUser ? <User className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
                </div>

                {/* Message Content */}
                <div className={cn(
                    "group relative rounded-2xl px-4 py-3 text-sm shadow-xs",
                    isUser
                        ? "bg-primary text-primary-foreground rounded-tr-none"
                        : "bg-muted/50 text-foreground border rounded-tl-none"
                )}>
                    {/* Markdown Content */}
                    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
                        <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                                code({ node, inline, className, children, ...props }: any) {
                                    return !inline ? (
                                        <div className="relative rounded-md bg-muted p-2 my-2 font-mono text-xs overflow-x-auto">
                                            <code {...props} className={className}>
                                                {children}
                                            </code>
                                        </div>
                                    ) : (
                                        <code {...props} className={cn("bg-muted px-1.5 py-0.5 rounded text-xs", className)}>
                                            {children}
                                        </code>
                                    )
                                }
                            }}
                        >
                            {content}
                        </ReactMarkdown>
                    </div>

                    {/* Copy Button (only visible on hover) */}
                    <Button
                        variant="ghost"
                        size="icon"
                        className="absolute -bottom-8 right-0 opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6"
                        onClick={copyToClipboard}
                    >
                        <Copy className="h-3 w-3" />
                    </Button>
                </div>
            </div>
        </div>
    );
}
