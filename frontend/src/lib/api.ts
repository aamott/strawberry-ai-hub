import axios from "axios";

// Create axios instance
export const api = axios.create({
    baseURL: "/api/admin", // Using relative path since we'll serve from FastAPI
    headers: {
        "Content-Type": "application/json",
    },
});

// Helper to set token
export const setAuthToken = (token: string | null) => {
    if (token) {
        localStorage.setItem("admin_token", token);
        api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    } else {
        localStorage.removeItem("admin_token");
        delete api.defaults.headers.common["Authorization"];
    }
};

// Request interceptor to add token from storage
api.interceptors.request.use((config) => {
    const token = localStorage.getItem("admin_token");
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Response interceptor to handle 401s
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            // Clear token and redirect to login if unauthorized
            setAuthToken(null);
            if (window.location.pathname !== "/login" && window.location.pathname !== "/setup") {
                window.location.href = "/login";
            }
        }
        return Promise.reject(error);
    }
);
