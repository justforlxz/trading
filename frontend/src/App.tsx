import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/app-shell";
import BacktestsPage from "./pages/backtests";
import InstrumentDetailPage from "./pages/instrument-detail";
import OverviewPage from "./pages/overview";
import RelationsPage from "./pages/relations";
import SettingsPage from "./pages/settings";
import StrategiesPage from "./pages/strategies";
import TradesPage from "./pages/trades";
import WatchlistPage from "./pages/watchlist";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="watchlist/:instId" element={<InstrumentDetailPage />} />
        <Route path="relations" element={<RelationsPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
