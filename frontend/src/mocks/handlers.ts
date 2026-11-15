// 由 `pnpm --dir frontend api:sync` 生成，勿手改。
// 数据一律来自 backend/contracts/openapi.json 的 example，handler 里不写业务常量。
import { HttpResponse, http } from "msw";

import getAccountSummary from "./fixtures/positions/get-account-summary.json";
import postAccountSync from "./fixtures/positions/post-account-sync.json";
import getActivity from "./fixtures/alerts/get-activity.json";
import postAiSummary from "./fixtures/ai/post-ai-summary.json";
import getAlerts from "./fixtures/alerts/get-alerts.json";
import patchAlertsAlertId from "./fixtures/alerts/patch-alerts-alert_id.json";
import getApprovals from "./fixtures/approval/get-approvals.json";
import postApprovals from "./fixtures/approval/post-approvals.json";
import postApprovalsInstanceIdApprove from "./fixtures/approval/post-approvals-instance_id-approve.json";
import postApprovalsInstanceIdLiveAuthorization from "./fixtures/approval/post-approvals-instance_id-live-authorization.json";
import postApprovalsInstanceIdReject from "./fixtures/approval/post-approvals-instance_id-reject.json";
import postBacktestSweeps from "./fixtures/backtest/post-backtest-sweeps.json";
import getBacktests from "./fixtures/backtest/get-backtests.json";
import postBacktests from "./fixtures/backtest/post-backtests.json";
import getBacktestsRanking from "./fixtures/backtest/get-backtests-ranking.json";
import getBacktestsRunId from "./fixtures/backtest/get-backtests-run_id.json";
import getBacktestsRunIdChart from "./fixtures/backtest/get-backtests-run_id-chart.json";
import getBacktestsRunIdEquity from "./fixtures/backtest/get-backtests-run_id-equity.json";
import getBacktestsRunIdReplay from "./fixtures/backtest/get-backtests-run_id-replay.json";
import getBacktestsRunIdTrades from "./fixtures/backtest/get-backtests-run_id-trades.json";
import getCorrelationMatrix from "./fixtures/correlation/get-correlation-matrix.json";
import getCorrelationSeries from "./fixtures/correlation/get-correlation-series.json";
import getDashboardSummary from "./fixtures/dashboard/get-dashboard-summary.json";
import getHealth from "./fixtures/health/get-health.json";
import getIndicators from "./fixtures/indicators/get-indicators.json";
import getIndicatorsSeries from "./fixtures/indicators/get-indicators-series.json";
import getInstruments from "./fixtures/instruments/get-instruments.json";
import getInstrumentsSearch from "./fixtures/instruments/get-instruments-search.json";
import getInstrumentsInstId from "./fixtures/instruments/get-instruments-inst_id.json";
import getInstrumentsInstIdAnalysis from "./fixtures/instruments/get-instruments-inst_id-analysis.json";
import getInstrumentsInstIdCandles from "./fixtures/instruments/get-instruments-inst_id-candles.json";
import getInstrumentsInstIdStrategies from "./fixtures/strategy/get-instruments-inst_id-strategies.json";
import getManualPositions from "./fixtures/positions/get-manual-positions.json";
import postManualPositions from "./fixtures/positions/post-manual-positions.json";
import patchManualPositionsPositionId from "./fixtures/positions/patch-manual-positions-position_id.json";
import getManualPositionsPositionIdTrades from "./fixtures/positions/get-manual-positions-position_id-trades.json";
import postManualPositionsPositionIdTrades from "./fixtures/positions/post-manual-positions-position_id-trades.json";
import getMarketBreadth from "./fixtures/market/get-market-breadth.json";
import getMarketEvents from "./fixtures/market/get-market-events.json";
import getMarketOverview from "./fixtures/market/get-market-overview.json";
import getNews from "./fixtures/market/get-news.json";
import getOpportunities from "./fixtures/opportunity/get-opportunities.json";
import getOpportunitiesOpportunityId from "./fixtures/opportunity/get-opportunities-opportunity_id.json";
import patchOpportunitiesOpportunityId from "./fixtures/opportunity/patch-opportunities-opportunity_id.json";
import getPositions from "./fixtures/positions/get-positions.json";
import getPositionsExchange from "./fixtures/positions/get-positions-exchange.json";
import putPositionsPositionRefRiskConfig from "./fixtures/risk/put-positions-position_ref-risk-config.json";
import getResearchNotes from "./fixtures/research/get-research-notes.json";
import postResearchNotes from "./fixtures/research/post-research-notes.json";
import getResearchNotesNoteId from "./fixtures/research/get-research-notes-note_id.json";
import putResearchNotesNoteId from "./fixtures/research/put-research-notes-note_id.json";
import getRiskEvents from "./fixtures/risk/get-risk-events.json";
import patchRiskEventsEventIdResolve from "./fixtures/risk/patch-risk-events-event_id-resolve.json";
import getRiskExposure from "./fixtures/risk/get-risk-exposure.json";
import getSettings from "./fixtures/settings/get-settings.json";
import patchSettings from "./fixtures/settings/patch-settings.json";
import getStrategies from "./fixtures/strategy/get-strategies.json";
import postStrategies from "./fixtures/strategy/post-strategies.json";
import getStrategiesStrategyId from "./fixtures/strategy/get-strategies-strategy_id.json";
import putStrategiesStrategyId from "./fixtures/strategy/put-strategies-strategy_id.json";
import getStrategiesStrategyIdVersions from "./fixtures/strategy/get-strategies-strategy_id-versions.json";
import postStrategiesStrategyIdVersions from "./fixtures/strategy/post-strategies-strategy_id-versions.json";
import putStrategiesStrategyIdVersionsVersionInstruments from "./fixtures/strategy/put-strategies-strategy_id-versions-version-instruments.json";
import getSystemHealth from "./fixtures/system/get-system-health.json";
import postSystemSync from "./fixtures/system/post-system-sync.json";
import getWatchlist from "./fixtures/watchlist/get-watchlist.json";
import postWatchlist from "./fixtures/watchlist/post-watchlist.json";
import patchWatchlistInstId from "./fixtures/watchlist/patch-watchlist-inst_id.json";
import getWatchlistInstIdRelated from "./fixtures/watchlist/get-watchlist-inst_id-related.json";

export const handlers = [
  http.get("*/api/account/summary", () => HttpResponse.json(getAccountSummary)),
  http.post("*/api/account/sync", () => HttpResponse.json(postAccountSync)),
  http.get("*/api/activity", () => HttpResponse.json(getActivity)),
  http.post("*/api/ai/summary", () => HttpResponse.json(postAiSummary)),
  http.get("*/api/alerts", () => HttpResponse.json(getAlerts)),
  http.patch("*/api/alerts/:alert_id", () => HttpResponse.json(patchAlertsAlertId)),
  http.get("*/api/approvals", () => HttpResponse.json(getApprovals)),
  http.post("*/api/approvals", () => HttpResponse.json(postApprovals, { status: 201 })),
  http.post("*/api/approvals/:instance_id/approve", () => HttpResponse.json(postApprovalsInstanceIdApprove)),
  http.post("*/api/approvals/:instance_id/live-authorization", () => HttpResponse.json(postApprovalsInstanceIdLiveAuthorization)),
  http.post("*/api/approvals/:instance_id/reject", () => HttpResponse.json(postApprovalsInstanceIdReject)),
  http.post("*/api/backtest-sweeps", () => HttpResponse.json(postBacktestSweeps, { status: 202 })),
  http.get("*/api/backtests", () => HttpResponse.json(getBacktests)),
  http.post("*/api/backtests", () => HttpResponse.json(postBacktests, { status: 202 })),
  http.get("*/api/backtests/ranking", () => HttpResponse.json(getBacktestsRanking)),
  http.get("*/api/backtests/:run_id", () => HttpResponse.json(getBacktestsRunId)),
  http.delete("*/api/backtests/:run_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/backtests/:run_id/chart", () => HttpResponse.json(getBacktestsRunIdChart)),
  http.get("*/api/backtests/:run_id/equity", () => HttpResponse.json(getBacktestsRunIdEquity)),
  http.get("*/api/backtests/:run_id/replay", () => HttpResponse.json(getBacktestsRunIdReplay)),
  http.get("*/api/backtests/:run_id/trades", () => HttpResponse.json(getBacktestsRunIdTrades)),
  http.get("*/api/backtests/:run_id/trades.csv", () => new HttpResponse(null, { status: 200 })),
  http.get("*/api/correlation/matrix", () => HttpResponse.json(getCorrelationMatrix)),
  http.get("*/api/correlation/series", () => HttpResponse.json(getCorrelationSeries)),
  http.get("*/api/dashboard/summary", () => HttpResponse.json(getDashboardSummary)),
  http.get("*/api/health", () => HttpResponse.json(getHealth)),
  http.get("*/api/indicators", () => HttpResponse.json(getIndicators)),
  http.get("*/api/indicators/series", () => HttpResponse.json(getIndicatorsSeries)),
  http.get("*/api/instruments", () => HttpResponse.json(getInstruments)),
  http.get("*/api/instruments/search", () => HttpResponse.json(getInstrumentsSearch)),
  http.get("*/api/instruments/:inst_id", () => HttpResponse.json(getInstrumentsInstId)),
  http.get("*/api/instruments/:inst_id/analysis", () => HttpResponse.json(getInstrumentsInstIdAnalysis)),
  http.get("*/api/instruments/:inst_id/candles", () => HttpResponse.json(getInstrumentsInstIdCandles)),
  http.get("*/api/instruments/:inst_id/strategies", () => HttpResponse.json(getInstrumentsInstIdStrategies)),
  http.get("*/api/manual-positions", () => HttpResponse.json(getManualPositions)),
  http.post("*/api/manual-positions", () => HttpResponse.json(postManualPositions, { status: 201 })),
  http.patch("*/api/manual-positions/:position_id", () => HttpResponse.json(patchManualPositionsPositionId)),
  http.delete("*/api/manual-positions/:position_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/manual-positions/:position_id/trades", () => HttpResponse.json(getManualPositionsPositionIdTrades)),
  http.post("*/api/manual-positions/:position_id/trades", () => HttpResponse.json(postManualPositionsPositionIdTrades, { status: 201 })),
  http.get("*/api/market/breadth", () => HttpResponse.json(getMarketBreadth)),
  http.get("*/api/market/events", () => HttpResponse.json(getMarketEvents)),
  http.get("*/api/market/overview", () => HttpResponse.json(getMarketOverview)),
  http.get("*/api/news", () => HttpResponse.json(getNews)),
  http.get("*/api/opportunities", () => HttpResponse.json(getOpportunities)),
  http.get("*/api/opportunities/:opportunity_id", () => HttpResponse.json(getOpportunitiesOpportunityId)),
  http.patch("*/api/opportunities/:opportunity_id", () => HttpResponse.json(patchOpportunitiesOpportunityId)),
  http.get("*/api/positions", () => HttpResponse.json(getPositions)),
  http.get("*/api/positions/exchange", () => HttpResponse.json(getPositionsExchange)),
  http.put("*/api/positions/:position_ref/risk-config", () => HttpResponse.json(putPositionsPositionRefRiskConfig)),
  http.get("*/api/research-notes", () => HttpResponse.json(getResearchNotes)),
  http.post("*/api/research-notes", () => HttpResponse.json(postResearchNotes, { status: 201 })),
  http.get("*/api/research-notes/:note_id", () => HttpResponse.json(getResearchNotesNoteId)),
  http.put("*/api/research-notes/:note_id", () => HttpResponse.json(putResearchNotesNoteId)),
  http.delete("*/api/research-notes/:note_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/risk/events", () => HttpResponse.json(getRiskEvents)),
  http.patch("*/api/risk/events/:event_id/resolve", () => HttpResponse.json(patchRiskEventsEventIdResolve)),
  http.get("*/api/risk/exposure", () => HttpResponse.json(getRiskExposure)),
  http.get("*/api/settings", () => HttpResponse.json(getSettings)),
  http.patch("*/api/settings", () => HttpResponse.json(patchSettings)),
  http.get("*/api/strategies", () => HttpResponse.json(getStrategies)),
  http.post("*/api/strategies", () => HttpResponse.json(postStrategies, { status: 201 })),
  http.get("*/api/strategies/:strategy_id", () => HttpResponse.json(getStrategiesStrategyId)),
  http.put("*/api/strategies/:strategy_id", () => HttpResponse.json(putStrategiesStrategyId)),
  http.get("*/api/strategies/:strategy_id/versions", () => HttpResponse.json(getStrategiesStrategyIdVersions)),
  http.post("*/api/strategies/:strategy_id/versions", () => HttpResponse.json(postStrategiesStrategyIdVersions, { status: 201 })),
  http.put("*/api/strategies/:strategy_id/versions/:version/instruments", () => HttpResponse.json(putStrategiesStrategyIdVersionsVersionInstruments)),
  http.get("*/api/system/health", () => HttpResponse.json(getSystemHealth)),
  http.post("*/api/system/sync", () => HttpResponse.json(postSystemSync, { status: 202 })),
  http.get("*/api/watchlist", () => HttpResponse.json(getWatchlist)),
  http.post("*/api/watchlist", () => HttpResponse.json(postWatchlist, { status: 201 })),
  http.patch("*/api/watchlist/:inst_id", () => HttpResponse.json(patchWatchlistInstId)),
  http.delete("*/api/watchlist/:inst_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/watchlist/:inst_id/related", () => HttpResponse.json(getWatchlistInstIdRelated)),
];
