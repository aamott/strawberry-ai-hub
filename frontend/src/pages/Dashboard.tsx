import { useState, useEffect } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, setAuthToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { LayoutDashboard, Settings, LogOut, Users, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";

export function Dashboard() {
    const [user, setUser] = useState<any>(null);
    const navigate = useNavigate();
    const location = useLocation();

    useEffect(() => {
        api.get("/users/me")
            .then((res) => setUser(res.data))
            .catch(() => navigate("/login"));
    }, [navigate]);

    const handleLogout = () => {
        setAuthToken(null);
        navigate("/login");
    };

    const navItems = [
        { icon: LayoutDashboard, label: "Overview", href: "/" },
        { icon: Users, label: "Users", href: "/users" },
        { icon: Cpu, label: "Devices", href: "/devices" },
        { icon: Settings, label: "Settings", href: "/settings" },
    ];

    if (!user) return null;

    return (
        <div className="flex min-h-screen bg-background text-foreground">
            {/* Sidebar */}
            <aside className="w-64 border-r bg-muted/20">
                <div className="p-6">
                    <h1 className="text-xl font-bold">🍓 Strawberry AI</h1>
                    <p className="text-xs text-muted-foreground mt-1">Hub Admin</p>
                </div>
                <nav className="space-y-1 px-4">
                    {navItems.map((item) => (
                        <Link
                            key={item.href}
                            to={item.href}
                            className={cn(
                                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                                location.pathname === item.href ? "bg-accent text-accent-foreground" : "text-muted-foreground"
                            )}
                        >
                            <item.icon className="h-4 w-4" />
                            {item.label}
                        </Link>
                    ))}
                </nav>
                <div className="absolute bottom-4 left-4 right-4">
                    <div className="flex items-center gap-3 px-3 py-2 mb-2">
                        <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary font-bold">
                            {user.username[0].toUpperCase()}
                        </div>
                        <div className="overflow-hidden">
                            <p className="text-sm font-medium truncate">{user.username}</p>
                            <p className="text-xs text-muted-foreground">Admin</p>
                        </div>
                    </div>
                    <Button variant="outline" className="w-full justify-start" onClick={handleLogout}>
                        <LogOut className="mr-2 h-4 w-4" />
                        Logout
                    </Button>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 p-8 overflow-auto">
                <Outlet />
            </main>
        </div>
    );
}
