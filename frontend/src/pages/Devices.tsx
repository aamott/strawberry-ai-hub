import { useState, useEffect, useCallback } from "react";
import type { AxiosError } from "axios";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogFooter,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
    Trash2, Plus, Monitor, Copy, ChevronRight, ChevronDown, Search,
} from "lucide-react";
import { useToast } from "@/components/ui/use-toast";

// --- Types ---

interface Device {
    id: string;
    name: string;
    is_active: boolean;
    last_seen?: string;
    created_at: string;
    skill_names: string[];
    skill_count: number;
}

interface NewDeviceResponse {
    device: Device;
    token: string;
    command: string;
}

// --- Helpers ---

function getApiErrorDetail(err: unknown): string | undefined {
    const axiosErr = err as AxiosError<{ detail?: string }>;
    return axiosErr?.response?.data?.detail;
}

/** Format an ISO timestamp as a human-friendly relative string. */
function relativeTime(iso: string | undefined): string {
    if (!iso) return "Never";
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diffSec = Math.floor((now - then) / 1000);
    if (diffSec < 60) return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 30) return `${diffDay}d ago`;
    return new Date(iso).toLocaleDateString();
}

// --- Components ---

/** Small pill badge for a skill class name. */
function SkillBadge({ name }: { name: string }) {
    return (
        <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
            {name}
        </span>
    );
}

/** A single accordion row for one device. */
function DeviceRow({
    device,
    isExpanded,
    onToggle,
    onDelete,
}: {
    device: Device;
    isExpanded: boolean;
    onToggle: () => void;
    onDelete: () => void;
}) {
    return (
        <div className="rounded-lg border bg-card text-card-foreground">
            {/* Collapsed header — always visible */}
            <button
                type="button"
                onClick={onToggle}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/50"
            >
                <Monitor className="h-4 w-4 shrink-0 text-muted-foreground" />

                {/* Device name */}
                <span className="font-medium text-sm min-w-0 truncate">
                    {device.name}
                </span>

                {/* Status dot + label */}
                <span className="flex items-center gap-1.5 shrink-0 ml-auto mr-2">
                    <span
                        className={`h-2 w-2 rounded-full ${
                            device.is_active ? "bg-green-500" : "bg-gray-400"
                        }`}
                    />
                    <span className="text-xs text-muted-foreground hidden sm:inline">
                        {device.is_active ? "Active" : "Inactive"}
                    </span>
                </span>

                {/* Skill count */}
                <span className="text-xs text-muted-foreground shrink-0 tabular-nums w-16 text-right hidden md:inline">
                    {device.skill_count} {device.skill_count === 1 ? "skill" : "skills"}
                </span>

                {/* Last seen */}
                <span className="text-xs text-muted-foreground shrink-0 tabular-nums w-16 text-right hidden lg:inline">
                    {relativeTime(device.last_seen)}
                </span>

                {/* Expand / collapse chevron */}
                {isExpanded ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
            </button>

            {/* Expanded detail area */}
            {isExpanded && (
                <div className="border-t px-4 py-3 space-y-3">
                    {/* Skill badges */}
                    {device.skill_count > 0 ? (
                        <div>
                            <p className="text-xs font-medium text-muted-foreground mb-2">
                                Skills ({device.skill_count})
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                                {device.skill_names.map((name) => (
                                    <SkillBadge key={name} name={name} />
                                ))}
                            </div>
                        </div>
                    ) : (
                        <p className="text-xs text-muted-foreground italic">
                            No skills registered on this device.
                        </p>
                    )}

                    {/* Meta row: last seen + created + delete */}
                    <div className="flex items-center justify-between pt-1">
                        <div className="flex gap-4 text-xs text-muted-foreground">
                            <span>Last seen: {relativeTime(device.last_seen)}</span>
                            <span className="hidden sm:inline">
                                Created: {new Date(device.created_at).toLocaleDateString()}
                            </span>
                        </div>
                        <Button
                            variant="destructive"
                            size="sm"
                            className="h-7 px-2"
                            onClick={(e) => {
                                e.stopPropagation();
                                onDelete();
                            }}
                        >
                            <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}

// --- Page ---

export function DevicesPage() {
    const [devices, setDevices] = useState<Device[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [open, setOpen] = useState(false);
    const [newDeviceName, setNewDeviceName] = useState("");
    const [createdDevice, setCreatedDevice] = useState<NewDeviceResponse | null>(null);
    const { toast } = useToast();

    const loadDevices = useCallback(async () => {
        try {
            const res = await api.get("/devices");
            setDevices(res.data);
        } catch (err) {
            console.error("Failed to load devices", err);
            toast({
                title: "Error",
                description: "Failed to load devices",
                variant: "destructive",
            });
        } finally {
            setLoading(false);
        }
    }, [toast]);

    useEffect(() => {
        void loadDevices();
    }, [loadDevices]);

    // Periodically refresh device data so the list stays accurate when
    // devices disconnect/reconnect or skills are re-registered.
    useEffect(() => {
        const intervalId = window.setInterval(() => {
            void loadDevices();
        }, 10_000); // 10s cadence keeps UI fresh without spamming the API.

        return () => window.clearInterval(intervalId);
    }, [loadDevices]);

    // --- Filter devices by search (name or skill names) ---
    const filteredDevices = devices.filter((d) => {
        if (!search.trim()) return true;
        const q = search.toLowerCase();
        if (d.name.toLowerCase().includes(q)) return true;
        return d.skill_names.some((s) => s.toLowerCase().includes(q));
    });

    // --- Expand / collapse ---
    const toggleExpand = (id: string) => {
        setExpandedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    // --- CRUD ---
    const handleDelete = async (id: string) => {
        if (!confirm("Are you sure you want to delete this device?")) return;
        try {
            await api.delete(`/devices/${id}`);
            toast({ title: "Device deleted" });
            setExpandedIds((prev) => {
                const next = new Set(prev);
                next.delete(id);
                return next;
            });
            await loadDevices();
        } catch (err: unknown) {
            console.error("Failed to delete device", err);
            toast({
                title: "Error",
                description: getApiErrorDetail(err) || "Failed to delete device",
                variant: "destructive",
            });
        }
    };

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const res = await api.post("/devices/token", { name: newDeviceName });
            setCreatedDevice(res.data);
            toast({ title: "Device created" });
            await loadDevices();
        } catch (err: unknown) {
            console.error("Failed to create device", err);
            toast({
                title: "Error",
                description: getApiErrorDetail(err) || "Failed to create device",
                variant: "destructive",
            });
        }
    };

    const handleCopy = () => {
        if (createdDevice) {
            navigator.clipboard.writeText(createdDevice.command);
            toast({ title: "Command copied to clipboard" });
        }
    };

    const handleCloseDialog = () => {
        setOpen(false);
        setCreatedDevice(null);
        setNewDeviceName("");
    };

    return (
        <div className="space-y-6">
            {/* Page header + Add Device */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">
                        Devices{!loading && ` (${devices.length})`}
                    </h2>
                    <p className="text-muted-foreground">Manage connected Spoke devices.</p>
                </div>
                <Dialog open={open} onOpenChange={(val) => !val && handleCloseDialog()}>
                    <DialogTrigger asChild>
                        <Button onClick={() => setOpen(true)}>
                            <Plus className="mr-2 h-4 w-4" />
                            Add Device
                        </Button>
                    </DialogTrigger>
                    <DialogContent className="sm:max-w-md">
                        <DialogHeader>
                            <DialogTitle>Add New Device</DialogTitle>
                            <DialogDescription>
                                Register a new device to generate an enrollment token.
                            </DialogDescription>
                        </DialogHeader>

                        {!createdDevice ? (
                            <form onSubmit={handleCreate}>
                                <div className="grid gap-4 py-4">
                                    <div className="grid gap-2">
                                        <Label htmlFor="name">Device Name</Label>
                                        <Input
                                            id="name"
                                            placeholder="e.g. Living Room Speaker"
                                            value={newDeviceName}
                                            onChange={(e) => setNewDeviceName(e.target.value)}
                                            required
                                        />
                                    </div>
                                </div>
                                <DialogFooter>
                                    <Button type="submit">Generate Token</Button>
                                </DialogFooter>
                            </form>
                        ) : (
                            <div className="space-y-4 py-4">
                                <div className="rounded-md bg-muted p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <Label className="text-xs font-medium uppercase text-muted-foreground">
                                            Run this command on the device
                                        </Label>
                                        <Button size="icon" variant="ghost" className="h-6 w-6" onClick={handleCopy}>
                                            <Copy className="h-3 w-3" />
                                        </Button>
                                    </div>
                                    <code className="text-xs break-all block bg-black text-white p-2 rounded border font-mono">
                                        {createdDevice.command}
                                    </code>
                                </div>
                                <div className="rounded-md border p-3">
                                    <Label className="text-xs text-muted-foreground">Token (for manual config)</Label>
                                    <p className="text-xs break-all mt-1 font-mono text-muted-foreground">
                                        {createdDevice.token}
                                    </p>
                                </div>
                                <DialogFooter>
                                    <Button onClick={handleCloseDialog}>Done</Button>
                                </DialogFooter>
                            </div>
                        )}
                    </DialogContent>
                </Dialog>
            </div>

            {/* Search bar — only show when there are devices */}
            {!loading && devices.length > 0 && (
                <div className="relative max-w-sm">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search devices or skills..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="pl-9"
                    />
                </div>
            )}

            {/* Device list */}
            {loading ? (
                <div className="text-center py-10">Loading...</div>
            ) : devices.length === 0 ? (
                <div className="text-center py-10 border-2 border-dashed rounded-lg">
                    <Monitor className="h-10 w-10 mx-auto text-muted-foreground mb-4" />
                    <h3 className="text-lg font-medium">No devices found</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                        Add your first device to get started.
                    </p>
                </div>
            ) : filteredDevices.length === 0 ? (
                <div className="text-center py-10 text-muted-foreground text-sm">
                    No devices match &ldquo;{search}&rdquo;
                </div>
            ) : (
                <div className="space-y-2">
                    {filteredDevices.map((device) => (
                        <DeviceRow
                            key={device.id}
                            device={device}
                            isExpanded={expandedIds.has(device.id)}
                            onToggle={() => toggleExpand(device.id)}
                            onDelete={() => handleDelete(device.id)}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
