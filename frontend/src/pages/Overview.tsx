import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, Monitor, Activity, Cpu } from "lucide-react";

type HubDevice = {
    is_active: boolean;
};

export function Overview() {
    const [stats, setStats] = useState<{
        username: string;
        isAdmin: boolean;
        users?: number;
        devices: number;
        activeDevices: number;
    }>({
        username: "",
        isAdmin: false,
        users: undefined,
        devices: 0,
        activeDevices: 0,
    });

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [meRes, devicesRes] = await Promise.all([
                    api.get("/users/me"),
                    api.get("/devices"),
                ]);

                const me = meRes.data;
                const devices = devicesRes.data as HubDevice[];
                const activeDevices = devices.filter((d) => d.is_active).length;

                if (me.is_admin) {
                    const usersRes = await api.get("/users");
                    setStats({
                        username: me.username,
                        isAdmin: true,
                        users: usersRes.data.length,
                        devices: devices.length,
                        activeDevices,
                    });
                    return;
                }

                setStats({
                    username: me.username,
                    isAdmin: false,
                    users: undefined,
                    devices: devices.length,
                    activeDevices,
                });
            } catch (err) {
                console.error("Failed to fetch stats", err);
            }
        };

        fetchData();
    }, []);

    return (
        <div className="space-y-6">
            <h2 className="text-3xl font-bold tracking-tight">Overview</h2>
            <div
                className={`grid gap-4 md:grid-cols-2 ${stats.isAdmin ? "lg:grid-cols-4" : "lg:grid-cols-3"}`}
            >
                {stats.isAdmin ? (
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Total Users</CardTitle>
                            <Users className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">{stats.users ?? 0}</div>
                            <p className="text-xs text-muted-foreground">Registered accounts</p>
                        </CardContent>
                    </Card>
                ) : (
                    <Card>
                        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                            <CardTitle className="text-sm font-medium">Account</CardTitle>
                            <Users className="h-4 w-4 text-muted-foreground" />
                        </CardHeader>
                        <CardContent>
                            <div className="text-2xl font-bold">{stats.username || "—"}</div>
                            <p className="text-xs text-muted-foreground">Signed in</p>
                        </CardContent>
                    </Card>
                )}
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Total Devices</CardTitle>
                        <Monitor className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{stats.devices}</div>
                        <p className="text-xs text-muted-foreground">Registered Spoke devices</p>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">Active Devices</CardTitle>
                        <Activity className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{stats.activeDevices}</div>
                        <p className="text-xs text-muted-foreground">Online now</p>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">System Status</CardTitle>
                        <Cpu className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold text-green-500">Healthy</div>
                        <p className="text-xs text-muted-foreground">All systems operational</p>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}
