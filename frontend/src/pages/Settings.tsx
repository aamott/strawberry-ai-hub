import { useState, useEffect } from "react";
import Editor from "@monaco-editor/react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Save, RefreshCw } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";

export function SettingsPage() {
    const [activeTab, setActiveTab] = useState("env");
    const [content, setContent] = useState("");
    const [loading, setLoading] = useState(false);
    const { toast } = useToast();

    const loadConfig = async (type: string) => {
        setLoading(true);
        try {
            const res = await api.get(`/config/${type}`);
            setContent(res.data.content);
        } catch (err) {
            toast({
                title: "Error",
                description: "Failed to load config",
                variant: "destructive",
            });
        } finally {
            setLoading(false);
        }
    };

    const saveConfig = async () => {
        setLoading(true);
        try {
            await api.post(`/config/${activeTab}`, { content });
            toast({
                title: "Saved",
                description: "Configuration updated successfully",
            });
        } catch (err) {
            toast({
                title: "Error",
                description: "Failed to save config",
                variant: "destructive",
            });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadConfig(activeTab);
    }, [activeTab]);

    return (
        <div className="space-y-6 flex flex-col h-full">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                    <h2 className="text-2xl md:text-3xl font-bold tracking-tight">Settings</h2>
                    <p className="text-muted-foreground text-sm md:text-base">Manage system configuration files.</p>
                </div>
                <div className="flex gap-2 w-full sm:w-auto">
                    <Button variant="outline" onClick={() => loadConfig(activeTab)} disabled={loading} className="flex-1 sm:flex-none">
                        <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        Reload
                    </Button>
                    <Button onClick={saveConfig} disabled={loading} className="flex-1 sm:flex-none">
                        <Save className="mr-2 h-4 w-4" />
                        Save Changes
                    </Button>
                </div>
            </div>

            <div className="flex flex-col md:flex-row gap-4 flex-1 min-h-0">
                <div className="w-full md:w-48 flex md:flex-col gap-2 overflow-x-auto pb-2 md:pb-0">
                    <Button
                        variant={activeTab === "env" ? "secondary" : "ghost"}
                        className="justify-start whitespace-nowrap"
                        onClick={() => setActiveTab("env")}
                    >
                        Environment (.env)
                    </Button>
                    <Button
                        variant={activeTab === "tensorzero" ? "secondary" : "ghost"}
                        className="justify-start whitespace-nowrap"
                        onClick={() => setActiveTab("tensorzero")}
                    >
                        TensorZero (toml)
                    </Button>
                </div>

                <Card className="flex-1 flex flex-col min-h-[400px]">
                    <CardHeader className="py-4 border-b">
                        <CardTitle className="text-sm font-mono">
                            {activeTab === "env" ? ".env" : "tensorzero.toml"}
                        </CardTitle>
                    </CardHeader>
                    <div className="flex-1 p-0 relative">
                        <div className="absolute inset-0">
                            <Editor
                                height="100%"
                                language={activeTab === "env" ? "shell" : "toml"}
                                theme="vs-dark"
                                value={content}
                                onChange={(value) => setContent(value || "")}
                                options={{
                                    minimap: { enabled: false },
                                    scrollBeyondLastLine: false,
                                    fontSize: 14,
                                    automaticLayout: true,
                                }}
                            />
                        </div>
                    </div>
                </Card>
            </div>
        </div>
    );
}
