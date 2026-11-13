import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/app-shell";
import BacktestsPage from "./pages/backtests";
import InstrumentDetailPage from "./pages/instrument-detail";
import JournalPage from "./pages/journal";
import OverviewPage from "./pages/overview";
import PositionsPage from "./pages/positions";
import SettingsPage from "./pages/settings";
import StrategiesPage from "./pages/strategies";
import WatchlistPage from "./pages/watchlist";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="watchlist/:instId" element={<InstrumentDetailPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="journal" element={<JournalPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
