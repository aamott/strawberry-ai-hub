import { useState, useEffect } from "react";
import Editor from "@monaco-editor/react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
// Tabs removed as we use buttons for navigation
import { Save, RefreshCw } from "lucide-react";
import { useToast } from "@/components/ui/use-toast"; // Need to create toast

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
                description: "Failed to load configuration",
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
                description: "Failed to save configuration",
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
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">Settings</h2>
                    <p className="text-muted-foreground">Manage system configuration files.</p>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" onClick={() => loadConfig(activeTab)} disabled={loading}>
                        <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        Reload
                    </Button>
                    <Button onClick={saveConfig} disabled={loading}>
                        <Save className="mr-2 h-4 w-4" />
                        Save Changes
                    </Button>
                </div>
            </div>

            <div className="flex gap-4">
                <div className="w-48 space-y-2">
                    <Button
                        variant={activeTab === "env" ? "secondary" : "ghost"}
                        className="w-full justify-start"
                        onClick={() => setActiveTab("env")}
                    >
                        Environment (.env)
                    </Button>
                    <Button
                        variant={activeTab === "tensorzero" ? "secondary" : "ghost"}
                        className="w-full justify-start"
                        onClick={() => setActiveTab("tensorzero")}
                    >
                        TensorZero (toml)
                    </Button>
                </div>

                <Card className="flex-1 h-[600px] flex flex-col">
                    <CardHeader className="py-4 border-b">
                        <CardTitle className="text-sm font-mono">
                            {activeTab === "env" ? ".env" : "tensorzero.toml"}
                        </CardTitle>
                    </CardHeader>
                    <div className="flex-1 p-0">
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
                            }}
                        />
                    </div>
                </Card>
            </div>
        </div>
    );
}
