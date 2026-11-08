import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/app-shell";
import AssistantPage from "./pages/assistant/index";
import BacktestDetailPage from "./pages/backtests/detail";
import DashboardPage from "./pages/dashboard";
import ResearchPage from "./pages/research/index";
import RiskPage from "./pages/risk/index";
import SettingsPage from "./pages/settings";
import StrategiesPage from "./pages/strategies/index";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="risk" element={<RiskPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="backtests/:id" element={<BacktestDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
