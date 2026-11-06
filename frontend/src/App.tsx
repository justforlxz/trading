import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/app-shell";
import DashboardPage from "./pages/dashboard";
import ResearchPage from "./pages/research";
import SettingsPage from "./pages/settings";
import StrategiesPage from "./pages/strategies";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
