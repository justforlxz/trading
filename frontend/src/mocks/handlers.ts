// 由 `pnpm --dir frontend api:sync` 生成，勿手改。
// 数据一律来自 backend/contracts/openapi.json 的 example，handler 里不写业务常量。
import { HttpResponse, http } from "msw";

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
import getCorrelationMatrix from "./fixtures/correlation/get-correlation-matrix.json";
import getCorrelationSeries from "./fixtures/correlation/get-correlation-series.json";
import getExecution from "./fixtures/trades/get-execution.json";
import putExecutionMode from "./fixtures/trades/put-execution-mode.json";
import getHealth from "./fixtures/health/get-health.json";
import getIndicators from "./fixtures/indicators/get-indicators.json";
import getIndicatorsSeries from "./fixtures/indicators/get-indicators-series.json";
import getInstruments from "./fixtures/instruments/get-instruments.json";
import getInstrumentsSearch from "./fixtures/instruments/get-instruments-search.json";
import getInstrumentsInstId from "./fixtures/instruments/get-instruments-inst_id.json";
import getInstrumentsInstIdCandles from "./fixtures/instruments/get-instruments-inst_id-candles.json";
import getJournal from "./fixtures/trades/get-journal.json";
import getMarketOverview from "./fixtures/market/get-market-overview.json";
import getOpportunities from "./fixtures/opportunity/get-opportunities.json";
import getOpportunitiesOpportunityId from "./fixtures/opportunity/get-opportunities-opportunity_id.json";
import patchOpportunitiesOpportunityId from "./fixtures/opportunity/patch-opportunities-opportunity_id.json";
import getOverview from "./fixtures/overview/get-overview.json";
import getPortfolioAdjustments from "./fixtures/portfolio/get-portfolio-adjustments.json";
import postPortfolioAdjustments from "./fixtures/portfolio/post-portfolio-adjustments.json";
import patchPortfolioAdjustmentsAdjustmentId from "./fixtures/portfolio/patch-portfolio-adjustments-adjustment_id.json";
import getPortfolioExposure from "./fixtures/portfolio/get-portfolio-exposure.json";
import getPortfolioStrategies from "./fixtures/portfolio/get-portfolio-strategies.json";
import getPortfolioStrategiesInstanceId from "./fixtures/portfolio/get-portfolio-strategies-instance_id.json";
import getRelationsGraph from "./fixtures/relations/get-relations-graph.json";
import getRelationsNeighbors from "./fixtures/relations/get-relations-neighbors.json";
import getRiskEvents from "./fixtures/risk/get-risk-events.json";
import patchRiskEventsEventIdResolve from "./fixtures/risk/patch-risk-events-event_id-resolve.json";
import getSettings from "./fixtures/settings/get-settings.json";
import putSettings from "./fixtures/settings/put-settings.json";
import getSignals from "./fixtures/trades/get-signals.json";
import getStrategies from "./fixtures/strategy/get-strategies.json";
import getStrategyInstances from "./fixtures/strategy/get-strategy-instances.json";
import postStrategyInstances from "./fixtures/strategy/post-strategy-instances.json";
import getStrategyInstancesInstanceId from "./fixtures/strategy/get-strategy-instances-instance_id.json";
import patchStrategyInstancesInstanceId from "./fixtures/strategy/patch-strategy-instances-instance_id.json";
import getStrategyInstancesInstanceIdReplays from "./fixtures/strategy/get-strategy-instances-instance_id-replays.json";
import postStrategyInstancesInstanceIdReplays from "./fixtures/strategy/post-strategy-instances-instance_id-replays.json";
import getTradesFills from "./fixtures/trades/get-trades-fills.json";
import getTradesOrders from "./fixtures/trades/get-trades-orders.json";
import postTradesOrders from "./fixtures/trades/post-trades-orders.json";
import getTradesPositions from "./fixtures/trades/get-trades-positions.json";
import getWatchlist from "./fixtures/watchlist/get-watchlist.json";
import postWatchlist from "./fixtures/watchlist/post-watchlist.json";
import patchWatchlistInstId from "./fixtures/watchlist/patch-watchlist-inst_id.json";
import putWatchlistInstIdAlert from "./fixtures/watchlist/put-watchlist-inst_id-alert.json";
import getWatchlistInstIdRelated from "./fixtures/watchlist/get-watchlist-inst_id-related.json";

export const handlers = [
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
  http.get("*/api/correlation/matrix", () => HttpResponse.json(getCorrelationMatrix)),
  http.get("*/api/correlation/series", () => HttpResponse.json(getCorrelationSeries)),
  http.get("*/api/execution", () => HttpResponse.json(getExecution)),
  http.put("*/api/execution/mode", () => HttpResponse.json(putExecutionMode)),
  http.get("*/api/health", () => HttpResponse.json(getHealth)),
  http.get("*/api/indicators", () => HttpResponse.json(getIndicators)),
  http.get("*/api/indicators/series", () => HttpResponse.json(getIndicatorsSeries)),
  http.get("*/api/instruments", () => HttpResponse.json(getInstruments)),
  http.get("*/api/instruments/search", () => HttpResponse.json(getInstrumentsSearch)),
  http.get("*/api/instruments/:inst_id", () => HttpResponse.json(getInstrumentsInstId)),
  http.get("*/api/instruments/:inst_id/candles", () => HttpResponse.json(getInstrumentsInstIdCandles)),
  http.get("*/api/journal", () => HttpResponse.json(getJournal)),
  http.get("*/api/market/overview", () => HttpResponse.json(getMarketOverview)),
  http.get("*/api/opportunities", () => HttpResponse.json(getOpportunities)),
  http.get("*/api/opportunities/:opportunity_id", () => HttpResponse.json(getOpportunitiesOpportunityId)),
  http.patch("*/api/opportunities/:opportunity_id", () => HttpResponse.json(patchOpportunitiesOpportunityId)),
  http.get("*/api/overview", () => HttpResponse.json(getOverview)),
  http.get("*/api/portfolio/adjustments", () => HttpResponse.json(getPortfolioAdjustments)),
  http.post("*/api/portfolio/adjustments", () => HttpResponse.json(postPortfolioAdjustments, { status: 201 })),
  http.patch("*/api/portfolio/adjustments/:adjustment_id", () => HttpResponse.json(patchPortfolioAdjustmentsAdjustmentId)),
  http.get("*/api/portfolio/exposure", () => HttpResponse.json(getPortfolioExposure)),
  http.get("*/api/portfolio/strategies", () => HttpResponse.json(getPortfolioStrategies)),
  http.get("*/api/portfolio/strategies/:instance_id", () => HttpResponse.json(getPortfolioStrategiesInstanceId)),
  http.get("*/api/relations/graph", () => HttpResponse.json(getRelationsGraph)),
  http.get("*/api/relations/neighbors", () => HttpResponse.json(getRelationsNeighbors)),
  http.get("*/api/risk/events", () => HttpResponse.json(getRiskEvents)),
  http.patch("*/api/risk/events/:event_id/resolve", () => HttpResponse.json(patchRiskEventsEventIdResolve)),
  http.get("*/api/settings", () => HttpResponse.json(getSettings)),
  http.put("*/api/settings", () => HttpResponse.json(putSettings)),
  http.get("*/api/signals", () => HttpResponse.json(getSignals)),
  http.get("*/api/strategies", () => HttpResponse.json(getStrategies)),
  http.get("*/api/strategy-instances", () => HttpResponse.json(getStrategyInstances)),
  http.post("*/api/strategy-instances", () => HttpResponse.json(postStrategyInstances, { status: 201 })),
  http.get("*/api/strategy-instances/:instance_id", () => HttpResponse.json(getStrategyInstancesInstanceId)),
  http.patch("*/api/strategy-instances/:instance_id", () => HttpResponse.json(patchStrategyInstancesInstanceId)),
  http.delete("*/api/strategy-instances/:instance_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/strategy-instances/:instance_id/replays", () => HttpResponse.json(getStrategyInstancesInstanceIdReplays)),
  http.post("*/api/strategy-instances/:instance_id/replays", () => HttpResponse.json(postStrategyInstancesInstanceIdReplays, { status: 201 })),
  http.get("*/api/trades/fills", () => HttpResponse.json(getTradesFills)),
  http.get("*/api/trades/orders", () => HttpResponse.json(getTradesOrders)),
  http.post("*/api/trades/orders", () => HttpResponse.json(postTradesOrders, { status: 201 })),
  http.delete("*/api/trades/orders/:order_id", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/trades/positions", () => HttpResponse.json(getTradesPositions)),
  http.get("*/api/watchlist", () => HttpResponse.json(getWatchlist)),
  http.post("*/api/watchlist", () => HttpResponse.json(postWatchlist, { status: 201 })),
  http.patch("*/api/watchlist/:inst_id", () => HttpResponse.json(patchWatchlistInstId)),
  http.delete("*/api/watchlist/:inst_id", () => new HttpResponse(null, { status: 204 })),
  http.put("*/api/watchlist/:inst_id/alert", () => HttpResponse.json(putWatchlistInstIdAlert)),
  http.delete("*/api/watchlist/:inst_id/alert", () => new HttpResponse(null, { status: 204 })),
  http.get("*/api/watchlist/:inst_id/related", () => HttpResponse.json(getWatchlistInstIdRelated)),
];
