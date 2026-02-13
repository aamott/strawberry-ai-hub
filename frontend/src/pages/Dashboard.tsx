import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, setAuthToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
    LayoutDashboard,
    Settings,
    LogOut,
    Users,
    Cpu,
    Menu,
    MessageSquare,
    MessageSquarePlus,
    Sun,
    Moon,
    Search,
    X,
    Pin,
    PinOff,
    Pencil,
    Trash2,
    CheckSquare,
    ArrowUpDown,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/useTheme";
import {
    ChatSessionProvider,
    useChatSessions,
    type Session,
    type SortBy,
    type FilterBy,
} from "@/contexts/ChatSessionContext";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Sidebar / Drawer content (shared between pinned desktop sidebar & mobile sheet)
// ---------------------------------------------------------------------------

function SidebarContent({
    user,
    onClose,
}: {
    user: HubUser;
    onClose: () => void;
}) {
    const location = useLocation();
    const navigate = useNavigate();

    const visibleNavItems = NAV_ITEMS.filter(
        (item) => !item.adminOnly || user.is_admin
    );

    const handleNavClick = (href: string) => {
        navigate(href);
        onClose();
    };

    return (
        <div className="flex flex-col h-full">
            {/* Navigation */}
            <nav className="px-3 pt-3 pb-2 space-y-0.5">
                {visibleNavItems.map((item) => {
                    const isActive = item.href === "/"
                        ? location.pathname === "/"
                        : location.pathname.startsWith(item.href);

                    return (
                        <button
                            key={item.href}
                            onClick={() => handleNavClick(item.href)}
                            className={cn("nav-item", isActive && "nav-item--active")}
                        >
                            <item.icon className="icon-base shrink-0" />
                            <span>{item.label}</span>
                        </button>
                    );
                })}
            </nav>

            <div className="border-t mx-3" />

            {/* Chat list (takes remaining space via flex-1) */}
            <div className="flex flex-col flex-1 min-h-0">
                <ChatListSection onClose={onClose} />
            </div>

            {/* Footer */}
            <SidebarFooter />
        </div>
    );
}

// ---------------------------------------------------------------------------
// Chat list section (search + header + scrollable list)
// ---------------------------------------------------------------------------

function ChatListSection({ onClose }: { onClose: () => void }) {
    const {
        sessions,
        activeSessionId,
        setActiveSessionId,
        createSession,
        deleteSession,
        deleteSessions,
        renameSession,
        pinnedIds,
        togglePin,
        sortBy,
        setSortBy,
        filterBy,
        setFilterBy,
    } = useChatSessions();

    const navigate = useNavigate();
    const [searchQuery, setSearchQuery] = useState("");
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editTitle, setEditTitle] = useState("");
    const [selectMode, setSelectMode] = useState(false);
    const [selected, setSelected] = useState<Record<string, boolean>>({});
    const [showSortMenu, setShowSortMenu] = useState(false);
    const sortRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!showSortMenu) return;
        const handler = (e: MouseEvent) => {
            if (sortRef.current && !sortRef.current.contains(e.target as Node)) {
                setShowSortMenu(false);
            }
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, [showSortMenu]);

    const selectedIds = useMemo(
        () => Object.entries(selected).filter(([, v]) => v).map(([k]) => k),
        [selected]
    );

    const { pinnedSessions, recentSessions } = useMemo(() => {
        let list = [...sessions];
        const q = searchQuery.trim().toLowerCase();
        if (q) {
            list = list.filter((s) =>
                (s.title || "New Chat").toLowerCase().includes(q)
            );
        }
        if (filterBy === "pinned") {
            list = list.filter((s) => pinnedIds.has(s.id));
        }
        const compareFn = (a: Session, b: Session) => {
            switch (sortBy) {
                case "alpha":
                    return (a.title || "New Chat").localeCompare(b.title || "New Chat");
                case "created":
                    return b.id.localeCompare(a.id);
                case "last_activity":
                default:
                    return new Date(b.last_activity).getTime() - new Date(a.last_activity).getTime();
            }
        };
        const pinned = list.filter((s) => pinnedIds.has(s.id)).sort(compareFn);
        const recent = list.filter((s) => !pinnedIds.has(s.id)).sort(compareFn);
        return { pinnedSessions: pinned, recentSessions: recent };
    }, [sessions, searchQuery, filterBy, sortBy, pinnedIds]);

    const handleNewChat = async () => {
        const id = await createSession();
        if (id) {
            navigate("/chat");
            onClose();
        }
    };

    const handleSelectChat = (id: string) => {
        if (selectMode) {
            setSelected((prev) => ({ ...prev, [id]: !prev[id] }));
            return;
        }
        setActiveSessionId(id);
        navigate("/chat");
        onClose();
    };

    const handleDelete = async (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        if (!confirm("Delete this chat?")) return;
        try { await deleteSession(id); } catch { /* toast handled elsewhere */ }
    };

    const handleBulkDelete = async () => {
        if (selectedIds.length === 0) return;
        if (!confirm(`Delete ${selectedIds.length} chat(s)?`)) return;
        try { await deleteSessions(selectedIds); } catch { /* noop */ }
        setSelected({});
        setSelectMode(false);
    };

    const startEditing = (s: Session) => {
        setEditingId(s.id);
        setEditTitle(s.title || "New Chat");
    };

    const finishEditing = async (id: string) => {
        if (editTitle.trim()) {
            try { await renameSession(id, editTitle.trim()); } catch { /* noop */ }
        }
        setEditingId(null);
    };

    const renderSession = (session: Session, isPinned: boolean) => {
        const isActive = activeSessionId === session.id;
        return (
            <div
                key={session.id}
                className={cn("group chat-row", isActive && "chat-row--active")}
                onClick={() => handleSelectChat(session.id)}
            >
                {selectMode ? (
                    <input
                        type="checkbox"
                        className="h-4 w-4 rounded border border-input accent-primary shrink-0 cursor-pointer"
                        checked={Boolean(selected[session.id])}
                        onChange={() => setSelected((p) => ({ ...p, [session.id]: !p[session.id] }))}
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : isPinned ? (
                    <Pin className="icon-md shrink-0 opacity-60 rotate-45" />
                ) : (
                    <MessageSquare className="icon-md shrink-0 opacity-60" />
                )}

                {editingId === session.id ? (
                    <Input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") finishEditing(session.id);
                            if (e.key === "Escape") setEditingId(null);
                        }}
                        onBlur={() => finishEditing(session.id)}
                        autoFocus
                        className="h-6 py-0 px-1 text-xs"
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : (
                    <div
                        className="flex-1 overflow-hidden"
                        onDoubleClick={(e) => { e.stopPropagation(); startEditing(session); }}
                    >
                        <p className="truncate leading-none mb-0.5 text-foreground/90 text-[13px]">
                            {session.title || "New Chat"}
                        </p>
                        <div className="flex items-center gap-1.5">
                            <span className="text-[10px] text-muted-foreground">
                                {formatDistanceToNow(new Date(session.last_activity), { addSuffix: true })}
                            </span>
                            {session.message_count > 0 && (
                                <span className="text-[10px] text-muted-foreground">
                                    · {session.message_count} msg{session.message_count !== 1 ? "s" : ""}
                                </span>
                            )}
                        </div>
                    </div>
                )}

                {/* Hover actions */}
                {!selectMode && (
                    <div className="hover-actions group-hover:opacity-100">
                        <Button
                            variant="ghost" size="icon"
                            className="hover-action-btn"
                            onClick={(e) => { e.stopPropagation(); togglePin(session.id); }}
                            title={isPinned ? "Unpin" : "Pin"}
                        >
                            {isPinned ? <PinOff className="icon-sm" /> : <Pin className="icon-sm" />}
                        </Button>
                        <Button
                            variant="ghost" size="icon"
                            className="hover-action-btn"
                            onClick={(e) => { e.stopPropagation(); startEditing(session); }}
                            title="Rename"
                        >
                            <Pencil className="icon-sm" />
                        </Button>
                        <Button
                            variant="ghost" size="icon"
                            className="hover-action-btn--danger"
                            onClick={(e) => handleDelete(e, session.id)}
                            title="Delete"
                        >
                            <Trash2 className="icon-sm" />
                        </Button>
                    </div>
                )}
            </div>
        );
    };

    const totalVisible = pinnedSessions.length + recentSessions.length;

    return (
        <>
            {/* Section header with search */}
            <div className="px-3 pt-3 pb-1.5 space-y-2">
                <div className="flex items-center justify-between">
                    <span className="section-label text-[11px]">
                        Chats
                    </span>
                    <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" className="sidebar-icon-btn" onClick={handleNewChat} title="New Chat">
                            <MessageSquarePlus className="icon-base" />
                        </Button>
                        <div className="relative" ref={sortRef}>
                            <Button variant="ghost" size="icon" className="sidebar-icon-btn" onClick={() => setShowSortMenu((p) => !p)} title="Sort & filter">
                                <ArrowUpDown className="icon-md" />
                            </Button>
                            {showSortMenu && (
                                <div className="floating-menu right-0 top-8 w-44">
                                    <p className="section-label px-2 py-1">Sort by</p>
                                    {([["last_activity", "Last activity"], ["created", "Created date"], ["alpha", "A – Z"]] as [SortBy, string][]).map(([val, label]) => (
                                        <button key={val} className={cn("floating-menu-item", sortBy === val && "floating-menu-item--active")} onClick={() => setSortBy(val)}>
                                            {label}
                                        </button>
                                    ))}
                                    <div className="my-1 border-t" />
                                    <p className="section-label px-2 py-1">Show</p>
                                    {([["all", "All chats"], ["pinned", "Pinned only"]] as [FilterBy, string][]).map(([val, label]) => (
                                        <button key={val} className={cn("floating-menu-item", filterBy === val && "floating-menu-item--active")} onClick={() => setFilterBy(val)}>
                                            {label}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        {sessions.length > 0 && (
                            <Button variant="ghost" size="icon" className="sidebar-icon-btn" onClick={() => { setSelectMode((p) => { if (p) setSelected({}); return !p; }); }} title={selectMode ? "Cancel" : "Select"}>
                                <CheckSquare className={cn("icon-md", selectMode && "text-primary")} />
                            </Button>
                        )}
                    </div>
                </div>

                {/* Search inside chats section */}
                <div className="relative">
                    <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                    <Input
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search chats..."
                        className="pl-8 h-8 text-sm bg-background"
                    />
                    {searchQuery && (
                        <button
                            className="absolute right-2 top-2 text-muted-foreground hover:text-foreground cursor-pointer"
                            onClick={() => setSearchQuery("")}
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {selectMode && (
                <div className="px-3 pb-1.5 flex items-center gap-2">
                    <Button variant="destructive" size="sm" className="h-7 text-xs flex-1 cursor-pointer" disabled={selectedIds.length === 0} onClick={handleBulkDelete}>
                        <Trash2 className="h-3 w-3 mr-1" /> Delete ({selectedIds.length})
                    </Button>
                    <Button variant="outline" size="sm" className="h-7 text-xs cursor-pointer" onClick={() => { setSelectMode(false); setSelected({}); }}>
                        Cancel
                    </Button>
                </div>
            )}

            <ScrollArea className="flex-1 px-2">
                {totalVisible === 0 ? (
                    <div className="text-center text-muted-foreground text-sm py-8 px-4">
                        {searchQuery ? "No matching chats." : "No chats yet. Start a new conversation!"}
                    </div>
                ) : (
                    <div className="space-y-0.5 pb-2">
                        {pinnedSessions.length > 0 && (
                            <>
                                <p className="section-label px-3 pt-2 pb-1">Pinned</p>
                                {pinnedSessions.map((s) => renderSession(s, true))}
                            </>
                        )}
                        {recentSessions.length > 0 && (
                            <>
                                {pinnedSessions.length > 0 && (
                                    <p className="section-label px-3 pt-3 pb-1">Recent</p>
                                )}
                                {recentSessions.map((s) => renderSession(s, false))}
                            </>
                        )}
                    </div>
                )}
            </ScrollArea>
        </>
    );
}

// ---------------------------------------------------------------------------
// Sidebar Footer (theme toggle)
// ---------------------------------------------------------------------------

function SidebarFooter() {
    const { theme, toggle: toggleTheme } = useTheme();
    const isDark = theme === "dark";

    return (
        <div className="border-t p-3 flex items-center gap-2">
            <Button
                variant="ghost" size="sm"
                className="flex-1 justify-start gap-2 text-muted-foreground cursor-pointer hover:text-foreground"
                onClick={toggleTheme}
            >
                {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                {isDark ? "Light mode" : "Dark mode"}
            </Button>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Account Dropdown (top-right of header)
// ---------------------------------------------------------------------------

function AccountDropdown({
    user,
    onLogout,
}: {
    user: HubUser;
    onLogout: () => void;
}) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) {
                setOpen(false);
            }
        };
        document.addEventListener("mousedown", handler);
        return () => document.removeEventListener("mousedown", handler);
    }, [open]);

    return (
        <div className="relative" ref={ref}>
            <button
                className="avatar-circle"
                onClick={() => setOpen((p) => !p)}
                title="Account"
            >
                {user.username[0]?.toUpperCase()}
            </button>
            {open && (
                <div className="floating-menu right-0 top-10 w-52 p-2">
                    <div className="px-2 py-2">
                        <p className="text-sm font-medium">{user.username}</p>
                        <p className="text-[11px] text-muted-foreground">
                            {user.is_admin ? "Administrator" : "User"}
                        </p>
                    </div>
                    <div className="border-t my-1" />
                    <button
                        className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded text-destructive hover:bg-destructive/10 cursor-pointer transition-colors"
                        onClick={() => { setOpen(false); onLogout(); }}
                    >
                        <LogOut className="h-4 w-4" />
                        Logout
                    </button>
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Dashboard (main layout)
// ---------------------------------------------------------------------------

/** Width of the pinned desktop sidebar. */
const SIDEBAR_W = "w-80";

export function Dashboard() {
    const [user, setUser] = useState<HubUser | null>(null);
    const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
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

    // Show a minimal loading state while checking auth.
    if (!user) {
        return (
            <div className="flex h-screen items-center justify-center bg-background text-muted-foreground">
                <span className="text-lg animate-pulse">🍓</span>
            </div>
        );
    }

    // Determine header center text: on /chat show active chat title, otherwise brand.
    const isChat = location.pathname === "/chat";

    return (
        <ChatSessionProvider>
            <div className="flex h-screen bg-background text-foreground">
                {/* ── Desktop pinned sidebar (md+) ── */}
                <aside
                    className={cn(
                        "hidden md:flex flex-col border-r shrink-0 sidebar-surface",
                        SIDEBAR_W
                    )}
                >
                    <SidebarContent
                        user={user}
                        onClose={() => { /* noop on desktop — sidebar stays open */ }}
                    />
                </aside>

                {/* ── Mobile Sheet overlay (<md) ── */}
                <Sheet open={mobileDrawerOpen} onOpenChange={setMobileDrawerOpen}>
                    <SheetContent side="left" className="p-0 w-80 sm:w-96">
                        <SidebarContent
                            user={user}
                            onClose={() => setMobileDrawerOpen(false)}
                        />
                    </SheetContent>
                </Sheet>

                {/* ── Right column: header + content ── */}
                <div className="flex flex-col flex-1 min-w-0 h-screen">
                    {/* Fixed Header — on mobile spans full width; on desktop spans right of sidebar */}
                    <header className="app-header">
                        {/* Hamburger — only on mobile */}
                        <Button
                            variant="ghost" size="icon"
                            className="h-9 w-9 shrink-0 cursor-pointer md:hidden"
                            onClick={() => setMobileDrawerOpen(true)}
                        >
                            <Menu className="icon-lg" />
                        </Button>

                        {/* Center: brand or chat title */}
                        <div className="flex-1 min-w-0">
                            {isChat ? (
                                <ChatTitleDisplay />
                            ) : (
                                <span className="font-semibold text-base">🍓 Strawberry AI</span>
                            )}
                        </div>

                        {/* Right: account */}
                        <AccountDropdown user={user} onLogout={handleLogout} />
                    </header>

                    {/* Main Content */}
                    <main className={cn(
                        "flex-1 overflow-auto",
                        isChat ? "p-0" : "p-4 md:p-8"
                    )}>
                        <Outlet />
                    </main>
                </div>
            </div>
        </ChatSessionProvider>
    );
}

/** Displays the active chat title in the header. */
function ChatTitleDisplay() {
    const { sessions, activeSessionId } = useChatSessions();
    const title = activeSessionId
        ? sessions.find((s) => s.id === activeSessionId)?.title || "Chat"
        : "New Chat";
    return (
        <span className="font-semibold text-base truncate block">
            🍓 {title}
        </span>
    );
}
