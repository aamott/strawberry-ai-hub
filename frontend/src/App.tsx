import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ToasterProvider } from "@/components/ui/use-toast";
import { Dashboard } from "@/pages/Dashboard";
import { Login } from "@/pages/Login";
import { Setup } from "@/pages/Setup";
import { SettingsPage } from "@/pages/Settings";
import { UsersPage } from "@/pages/Users";
import { DevicesPage } from "@/pages/Devices";
import { Overview } from "@/pages/Overview";

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
