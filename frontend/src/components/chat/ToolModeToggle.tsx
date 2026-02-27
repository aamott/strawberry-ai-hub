import { Code2, Wrench, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ToolModeToggleProps {
    mode: string;
    onChange: (mode: string) => void;
    locked: boolean;
}

const MODE_CONFIG: Record<string, { label: string; icon: typeof Code2; desc: string }> = {
    python_exec: {
        label: "Code",
        icon: Code2,
        desc: "LLM writes Python code to call skills",
    },
    native: {
        label: "Native",
        icon: Wrench,
        desc: "LLM calls skills directly as tools",
    },
};

export function ToolModeToggle({ mode, onChange, locked }: ToolModeToggleProps) {
    const config = MODE_CONFIG[mode] ?? MODE_CONFIG.python_exec;
    const Icon = config.icon;

    if (locked) {
        return (
            <div className="flex items-center gap-1.5 mb-2 text-xs text-muted-foreground">
                <Lock className="h-3 w-3" />
                <Icon className="h-3 w-3" />
                <span>{config.label} mode</span>
            </div>
        );
    }

    const nextMode = mode === "python_exec" ? "native" : "python_exec";

    return (
        <div className="flex items-center gap-2 mb-2">
            <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground gap-1.5"
                onClick={() => onChange(nextMode)}
                title={config.desc}
            >
                <Icon className="h-3.5 w-3.5" />
                {config.label} mode
            </Button>
        </div>
    );
}
