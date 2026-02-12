import { useState, useEffect, useCallback } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "theme";

function getSystemTheme(): Theme {
    if (typeof window === "undefined") return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getStoredTheme(): Theme | null {
    try {
        const v = localStorage.getItem(STORAGE_KEY);
        if (v === "light" || v === "dark") return v;
    } catch { /* noop */ }
    return null;
}

function applyTheme(theme: Theme) {
    document.documentElement.classList.toggle("dark", theme === "dark");
}

/**
 * Hook that manages light/dark theme with localStorage persistence.
 * Falls back to system preference if no stored value exists.
 */
export function useTheme() {
    const [theme, setThemeState] = useState<Theme>(() => {
        const stored = getStoredTheme();
        const resolved = stored ?? getSystemTheme();
        applyTheme(resolved);
        return resolved;
    });

    // Keep the DOM class in sync if theme changes.
    useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    const setTheme = useCallback((t: Theme) => {
        setThemeState(t);
        try {
            localStorage.setItem(STORAGE_KEY, t);
        } catch { /* noop */ }
    }, []);

    const toggle = useCallback(() => {
        setTheme(theme === "dark" ? "light" : "dark");
    }, [theme, setTheme]);

    return { theme, setTheme, toggle } as const;
}
