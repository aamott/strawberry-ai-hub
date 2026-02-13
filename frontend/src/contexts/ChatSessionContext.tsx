import {
    createContext,
    useContext,
    useState,
    useCallback,
    useEffect,
    type ReactNode,
} from "react";
import { api } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Session {
    id: string;
    title?: string;
    last_activity: string;
    message_count: number;
}

export type SortBy = "last_activity" | "created" | "alpha";
export type FilterBy = "all" | "pinned";

interface ChatSessionContextType {
    /** All sessions from the server. */
    sessions: Session[];
    /** Currently-viewed session. */
    activeSessionId: string | undefined;
    setActiveSessionId: (id: string | undefined) => void;

    /** Refresh the session list from the server. */
    fetchSessions: () => Promise<void>;
    /** Create a new session and return its ID. */
    createSession: () => Promise<string | undefined>;
    /** Delete a single session. */
    deleteSession: (id: string) => Promise<void>;
    /** Bulk-delete sessions. */
    deleteSessions: (ids: string[]) => Promise<void>;
    /** Rename a session. */
    renameSession: (id: string, title: string) => Promise<void>;

    /** Set of pinned session IDs (persisted in localStorage). */
    pinnedIds: Set<string>;
    /** Toggle pin state for a session. */
    togglePin: (id: string) => void;

    /** Sort preference. */
    sortBy: SortBy;
    setSortBy: (s: SortBy) => void;
    /** Filter preference. */
    filterBy: FilterBy;
    setFilterBy: (f: FilterBy) => void;
}

// ---------------------------------------------------------------------------
// localStorage helpers for pinned chats
// ---------------------------------------------------------------------------

const PINNED_KEY = "pinned_chats";

function readPinned(): Set<string> {
    try {
        const raw = localStorage.getItem(PINNED_KEY);
        if (raw) return new Set(JSON.parse(raw) as string[]);
    } catch { /* noop */ }
    return new Set();
}

function writePinned(ids: Set<string>) {
    try {
        localStorage.setItem(PINNED_KEY, JSON.stringify([...ids]));
    } catch { /* noop */ }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ChatSessionContext = createContext<ChatSessionContextType | null>(null);

/** Hook to consume session context. Throws if used outside provider. */
export function useChatSessions(): ChatSessionContextType {
    const ctx = useContext(ChatSessionContext);
    if (!ctx) throw new Error("useChatSessions must be used within ChatSessionProvider");
    return ctx;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ChatSessionProvider({ children }: { children: ReactNode }) {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [activeSessionId, setActiveSessionId] = useState<string | undefined>();
    const [pinnedIds, setPinnedIds] = useState<Set<string>>(readPinned);
    const [sortBy, setSortBy] = useState<SortBy>("last_activity");
    const [filterBy, setFilterBy] = useState<FilterBy>("all");

    // Persist pins whenever they change.
    useEffect(() => {
        writePinned(pinnedIds);
    }, [pinnedIds]);

    const fetchSessions = useCallback(async () => {
        try {
            const res = await api.get("/sessions");
            setSessions(res.data.sessions);
        } catch (error) {
            console.error("Failed to fetch sessions", error);
        }
    }, []);

    // Initial load.
    useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    const createSession = useCallback(async (): Promise<string | undefined> => {
        try {
            const res = await api.post("/sessions", {});
            const newSession: Session = res.data;
            setSessions((prev) => [newSession, ...prev]);
            setActiveSessionId(newSession.id);
            return newSession.id;
        } catch (error) {
            console.error("Failed to create session", error);
            return undefined;
        }
    }, []);

    const deleteSession = useCallback(async (id: string) => {
        await api.delete(`/sessions/${id}`);
        setSessions((prev) => prev.filter((s) => s.id !== id));
        // Clean up pin if needed.
        setPinnedIds((prev) => {
            if (!prev.has(id)) return prev;
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
        if (activeSessionId === id) {
            setActiveSessionId(undefined);
        }
    }, [activeSessionId]);

    const deleteSessions = useCallback(async (ids: string[]) => {
        for (const id of ids) {
            await api.delete(`/sessions/${id}`);
        }
        await fetchSessions();
        // Clean up pins.
        setPinnedIds((prev) => {
            const next = new Set(prev);
            for (const id of ids) next.delete(id);
            return next;
        });
        if (activeSessionId && ids.includes(activeSessionId)) {
            setActiveSessionId(undefined);
        }
    }, [activeSessionId, fetchSessions]);

    const renameSession = useCallback(async (id: string, title: string) => {
        await api.patch(`/sessions/${id}`, { title });
        setSessions((prev) =>
            prev.map((s) => (s.id === id ? { ...s, title } : s))
        );
    }, []);

    const togglePin = useCallback((id: string) => {
        setPinnedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }, []);

    return (
        <ChatSessionContext.Provider
            value={{
                sessions,
                activeSessionId,
                setActiveSessionId,
                fetchSessions,
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
            }}
        >
            {children}
        </ChatSessionContext.Provider>
    );
}
