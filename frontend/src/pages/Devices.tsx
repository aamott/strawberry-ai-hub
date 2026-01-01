import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Trash2, Plus, Monitor, Copy } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";

interface Device {
    id: string;
    name: string;
    is_active: boolean;
    last_seen?: string;
    created_at: string;
}

interface NewDeviceResponse {
    device: Device;
    token: string;
    command: string;
}

export function DevicesPage() {
    const [devices, setDevices] = useState<Device[]>([]);
    const [loading, setLoading] = useState(true);
    const [open, setOpen] = useState(false);
    const [newDeviceName, setNewDeviceName] = useState("");
    const [createdDevice, setCreatedDevice] = useState<NewDeviceResponse | null>(null);
    const { toast } = useToast();

    const loadDevices = async () => {
        try {
            const res = await api.get("/devices");
            setDevices(res.data);
        } catch (err) {
            toast({
                title: "Error",
                description: "Failed to load devices",
                variant: "destructive",
            });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadDevices();
    }, []);

    const handleDelete = async (id: string) => {
        if (!confirm("Are you sure you want to delete this device?")) return;
        try {
            await api.delete(`/devices/${id}`);
            toast({ title: "Device deleted" });
            loadDevices();
        } catch (err: any) {
            toast({
                title: "Error",
                description: err.response?.data?.detail || "Failed to delete device",
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
            loadDevices();
        } catch (err: any) {
            toast({
                title: "Error",
                description: err.response?.data?.detail || "Failed to create device",
                variant: "destructive",
            });
        }
    };

    const handleCopy = () => {
        if (createdDevice) {
            navigator.clipboard.writeText(createdDevice.command);
            toast({ title: "Command copied to clipboard" });
        }
    }

    const handleCloseDialog = () => {
        setOpen(false);
        setCreatedDevice(null);
        setNewDeviceName("");
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">Devices</h2>
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
                                        <Label className="text-xs font-medium uppercase text-muted-foreground">Run this command on the device</Label>
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
                                    <p className="text-xs break-all mt-1 font-mono text-muted-foreground">{createdDevice.token}</p>
                                </div>
                                <DialogFooter>
                                    <Button onClick={handleCloseDialog}>Done</Button>
                                </DialogFooter>
                            </div>
                        )}
                    </DialogContent>
                </Dialog>
            </div>

            {loading ? (
                <div className="text-center py-10">Loading...</div>
            ) : devices.length === 0 ? (
                <div className="text-center py-10 border-2 border-dashed rounded-lg">
                    <Monitor className="h-10 w-10 mx-auto text-muted-foreground mb-4" />
                    <h3 className="text-lg font-medium">No devices found</h3>
                    <p className="text-sm text-muted-foreground mt-1">Add your first device to get started.</p>
                </div>
            ) : (
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {devices.map((device) => (
                        <Card key={device.id}>
                            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                                <CardTitle className="text-sm font-medium">
                                    {device.name}
                                </CardTitle>
                                <Monitor className="h-4 w-4 text-muted-foreground" />
                            </CardHeader>
                            <CardContent>
                                <div className="mt-2 flex items-center gap-2">
                                    <div className={`h-2 w-2 rounded-full ${device.is_active ? 'bg-green-500' : 'bg-gray-300'}`} />
                                    <span className="text-sm text-muted-foreground">{device.is_active ? "Active" : "Inactive"}</span>
                                </div>
                                <div className="text-xs text-muted-foreground mt-2">
                                    Last Seen: {device.last_seen ? new Date(device.last_seen).toLocaleDateString() + ' ' + new Date(device.last_seen).toLocaleTimeString() : "Never"}
                                </div>
                                <div className="mt-4 flex justify-end">
                                    <Button variant="destructive" size="sm" onClick={() => handleDelete(device.id)}>
                                        <Trash2 className="h-4 w-4" />
                                    </Button>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </div>
            )}
        </div>
    );
}
