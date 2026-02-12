import { useState, useEffect, useCallback } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, setAuthToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
    LayoutDashboard,
    Settings,
    LogOut,
    Users,
    Cpu,
    Menu,
    MessageSquare,
    PanelLeftClose,
    PanelLeftOpen,
    Sun,
    Moon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/useTheme";

type HubUser = {
    id?: string;
    username: string;
    is_admin: boolean;
};

type NavItem = {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
    href: string;
    adminOnly: boolean;
};

const NAV_ITEMS: NavItem[] = [
    { icon: LayoutDashboard, label: "Overview", href: "/", adminOnly: false },
    { icon: MessageSquare, label: "Chat", href: "/chat", adminOnly: false },
    { icon: Cpu, label: "My Devices", href: "/devices", adminOnly: false },
    { icon: Users, label: "Users", href: "/users", adminOnly: true },
    { icon: Settings, label: "Settings", href: "/settings", adminOnly: true },
];

/** Persists the collapsed state across sessions. */
const SIDEBAR_KEY = "sidebar_collapsed";

function readCollapsed(): boolean {
    try {
        return localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
        return false;
    }
}

function writeCollapsed(v: boolean) {
    try {
        localStorage.setItem(SIDEBAR_KEY, v ? "1" : "0");
    } catch { /* noop */ }
}

/** Shared nav content used in both mobile sheet and desktop sidebar. */
function DashboardNavContent(props: {
    user: HubUser;
    visibleItems: NavItem[];
    pathname: string;
    collapsed: boolean;
    isDark: boolean;
    onToggle?: () => void;
    onToggleTheme: () => void;
    onNavigate: () => void;
    onLogout: () => void;
}) {
    const { user, visibleItems, pathname, collapsed, isDark, onToggle, onToggleTheme, onNavigate, onLogout } = props;

    return (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className={cn("flex items-center border-b", collapsed ? "justify-center p-3" : "justify-between p-4")}>
                {collapsed ? (
                    <span className="text-lg" role="img" aria-label="Strawberry AI">🍓</span>
                ) : (
                    <>
                        <div>
                            <h1 className="text-lg font-bold leading-tight">🍓 Strawberry AI</h1>
                            <p className="text-[10px] text-muted-foreground mt-0.5">
                                {user.is_admin ? "Hub Admin" : "User Portal"}
                            </p>
                        </div>
                    </>
                )}
                {onToggle && (
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onToggle}>
                        {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                    </Button>
                )}
            </div>

            {/* Navigation */}
            <nav className={cn("flex-1 space-y-1 py-3", collapsed ? "px-2" : "px-3")}>
                {visibleItems.map((item) => {
                    const isActive = item.href === "/"
                        ? pathname === "/"
                        : pathname.startsWith(item.href);

                    return (
                        <Link
                            key={item.href}
                            to={item.href}
                            onClick={onNavigate}
                            title={collapsed ? item.label : undefined}
                            className={cn(
                                "flex items-center gap-3 rounded-lg text-sm font-medium transition-colors",
                                collapsed ? "justify-center px-2 py-2.5" : "px-3 py-2",
                                isActive
                                    ? "bg-primary/10 text-primary"
                                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                            )}
                        >
                            <item.icon className="h-4 w-4 shrink-0" />
                            {!collapsed && <span>{item.label}</span>}
                        </Link>
                    );
                })}
            </nav>

            {/* User footer */}
            <div className={cn("border-t", collapsed ? "p-2" : "p-3")}>
                {collapsed ? (
                    <div className="flex flex-col items-center gap-2">
                        <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary font-bold text-xs">
                            {user.username[0]?.toUpperCase()}
                        </div>
                        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggleTheme} title={isDark ? "Light mode" : "Dark mode"}>
                            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onLogout} title="Logout">
                            <LogOut className="h-4 w-4" />
                        </Button>
                    </div>
                ) : (
                    <>
                        <div className="flex items-center gap-3 px-2 py-2 mb-2">
                            <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center text-primary font-bold text-xs shrink-0">
                                {user.username[0]?.toUpperCase()}
                            </div>
                            <div className="overflow-hidden">
                                <p className="text-sm font-medium truncate">{user.username}</p>
                                <p className="text-[11px] text-muted-foreground">
                                    {user.is_admin ? "Administrator" : "User"}
                                </p>
                            </div>
                        </div>
                        <div className="flex gap-2">
                            <Button variant="outline" className="flex-1 justify-start" size="sm" onClick={onLogout}>
                                <LogOut className="mr-2 h-4 w-4" />
                                Logout
                            </Button>
                            <Button variant="outline" size="sm" className="px-2.5" onClick={onToggleTheme} title={isDark ? "Light mode" : "Dark mode"}>
                                {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                            </Button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

export function Dashboard() {
    const [user, setUser] = useState<HubUser | null>(null);
    const [mobileOpen, setMobileOpen] = useState(false);
    const [collapsed, setCollapsed] = useState(readCollapsed);
    const { theme, toggle: toggleTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();

    useEffect(() => {
        if (!user) {
            api.get("/users/me")
                .then((res) => setUser(res.data as HubUser))
                .catch((err) => {
                    console.error("Failed to load current user", err);
                    navigate("/login");
                });
        }
    }, [user, navigate]);

    const handleLogout = useCallback(() => {
        setAuthToken(null);
        navigate("/login");
    }, [navigate]);

    const toggleCollapsed = useCallback(() => {
        setCollapsed((prev) => {
            const next = !prev;
            writeCollapsed(next);
            return next;
        });
    }, []);

    // Show a minimal loading state while checking auth (avoids blank flash)
    if (!user) {
        return (
            <div className="flex h-screen items-center justify-center bg-background text-muted-foreground">
                <span className="text-lg animate-pulse">🍓</span>
            </div>
        );
    }

    const visibleItems = NAV_ITEMS.filter((item) => !item.adminOnly || user.is_admin);

    return (
        <div className="flex h-screen bg-background text-foreground">
            {/* Mobile Header */}
            <header className="md:hidden fixed top-0 inset-x-0 z-30 border-b bg-background/95 backdrop-blur px-4 py-3 flex items-center gap-3">
                <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
                    <SheetTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-9 w-9">
                            <Menu className="h-5 w-5" />
                        </Button>
                    </SheetTrigger>
                    <SheetContent side="left" className="p-0 w-72 border-r">
                        <DashboardNavContent
                            user={user}
                            visibleItems={visibleItems}
                            pathname={location.pathname}
                            collapsed={false}
                            isDark={theme === "dark"}
                            onToggleTheme={toggleTheme}
                            onNavigate={() => setMobileOpen(false)}
                            onLogout={handleLogout}
                        />
                    </SheetContent>
                </Sheet>
                <span className="font-semibold text-base">🍓 Strawberry AI</span>
            </header>

            {/* Desktop Sidebar — collapsible */}
            <aside
                className={cn(
                    "hidden md:flex flex-col border-r bg-muted/40 transition-[width] duration-200 ease-in-out shrink-0",
                    collapsed ? "w-16" : "w-60"
                )}
            >
                <DashboardNavContent
                    user={user}
                    visibleItems={visibleItems}
                    pathname={location.pathname}
                    collapsed={collapsed}
                    isDark={theme === "dark"}
                    onToggle={toggleCollapsed}
                    onToggleTheme={toggleTheme}
                    onNavigate={() => undefined}
                    onLogout={handleLogout}
                />
            </aside>

            {/* Main Content */}
            <main className={cn(
                "flex-1 overflow-auto",
                "pt-[57px] md:pt-0",   // offset for mobile fixed header
                "h-screen",
                location.pathname === "/chat" ? "p-0" : "p-4 md:p-8"
            )}>
                <Outlet />
            </main>
        </div>
    );
}
