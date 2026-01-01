import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ToasterProvider } from "@/components/ui/use-toast";
import { Dashboard } from "@/pages/Dashboard";
import { Login } from "@/pages/Login";
import { Setup } from "@/pages/Setup";
import { SettingsPage } from "@/pages/Settings";

// Placeholders for now
const Overview = () => (
  <div className="space-y-4">
    <h2 className="text-3xl font-bold tracking-tight">Overview</h2>
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
        <div className="text-sm font-medium">Total Devices</div>
        <div className="text-2xl font-bold">--</div>
      </div>
      <div className="rounded-xl border bg-card text-card-foreground shadow p-6">
        <div className="text-sm font-medium">Active Sessions</div>
        <div className="text-2xl font-bold">--</div>
      </div>
    </div>
  </div>
);

const UsersPage = () => (
  <div>
    <h2 className="text-3xl font-bold tracking-tight mb-4">Users</h2>
    <p>User management coming soon.</p>
  </div>
);

const DevicesPage = () => (
  <div>
    <h2 className="text-3xl font-bold tracking-tight mb-4">Devices</h2>
    <p>Device management coming soon.</p>
  </div>
);

function App() {
  return (
    <ToasterProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />

          <Route path="/" element={<Dashboard />}>
            <Route index element={<Overview />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="devices" element={<DevicesPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ToasterProvider>
  );
}

export default App;
