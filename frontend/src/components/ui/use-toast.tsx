// Simplified hook based on shadcn/ui
import * as React from "react"
import { createContext, useContext, useState } from "react"

// Removed bad imports

type ToastType = {
    id: string;
    title?: string;
    description?: string;
    variant?: "default" | "destructive";
}

const ToastContext = createContext<{
    toast: (props: Omit<ToastType, "id">) => void;
}>({ toast: () => { } });

export function ToasterProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<ToastType[]>([]);

    const toast = (props: Omit<ToastType, "id">) => {
        const id = Math.random().toString(36);
        setToasts((prev) => [...prev, { id, ...props }]);
        setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
        }, 3000);
    };

    return (
        <ToastContext.Provider value={{ toast }}>
            {children}
            <div className="fixed bottom-0 right-0 z-50 p-4 space-y-4 max-w-md w-full pointer-events-none">
                {toasts.map((t) => (
                    <div
                        key={t.id}
                        className={`pointer-events-auto flex w-full flex-col gap-1 rounded-lg border p-4 shadow-lg transition-all ${t.variant === "destructive"
                                ? "bg-destructive text-destructive-foreground border-destructive"
                                : "bg-background text-foreground border-border"
                            }`}
                    >
                        {t.title && <div className="text-sm font-semibold">{t.title}</div>}
                        {t.description && <div className="text-sm opacity-90">{t.description}</div>}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}

export const useToast = () => {
    const context = useContext(ToastContext)
    return { toast: context.toast }
};
