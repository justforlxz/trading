// 由 `pnpm --dir frontend api:sync` 生成，勿手改。
// 数据一律来自 backend/contracts/openapi.json 的 example，handler 里不写业务常量。
import { HttpResponse, http } from "msw";

import postBacktestSweeps from "./fixtures/backtest/post-backtest-sweeps.json";
import getBacktests from "./fixtures/backtest/get-backtests.json";
import postBacktests from "./fixtures/backtest/post-backtests.json";
import getBacktestsRanking from "./fixtures/backtest/get-backtests-ranking.json";
import getBacktestsRunId from "./fixtures/backtest/get-backtests-run_id.json";
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
import getOverview from "./fixtures/overview/get-overview.json";
import getSettings from "./fixtures/settings/get-settings.json";
import putSettings from "./fixtures/settings/put-settings.json";
import getSignals from "./fixtures/trades/get-signals.json";
import getStrategies from "./fixtures/strategy/get-strategies.json";
import getStrategyInstances from "./fixtures/strategy/get-strategy-instances.json";
import postStrategyInstances from "./fixtures/strategy/post-strategy-instances.json";
import getStrategyInstancesInstanceId from "./fixtures/strategy/get-strategy-instances-instance_id.json";
import patchStrategyInstancesInstanceId from "./fixtures/strategy/patch-strategy-instances-instance_id.json";
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
  http.post("*/api/backtest-sweeps", () => HttpResponse.json(postBacktestSweeps, { status: 202 })),
  http.get("*/api/backtests", () => HttpResponse.json(getBacktests)),
  http.post("*/api/backtests", () => HttpResponse.json(postBacktests, { status: 202 })),
  http.get("*/api/backtests/ranking", () => HttpResponse.json(getBacktestsRanking)),
  http.get("*/api/backtests/:run_id", () => HttpResponse.json(getBacktestsRunId)),
  http.delete("*/api/backtests/:run_id", () => new HttpResponse(null, { status: 204 })),
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
  http.get("*/api/overview", () => HttpResponse.json(getOverview)),
  http.get("*/api/settings", () => HttpResponse.json(getSettings)),
  http.put("*/api/settings", () => HttpResponse.json(putSettings)),
  http.get("*/api/signals", () => HttpResponse.json(getSignals)),
  http.get("*/api/strategies", () => HttpResponse.json(getStrategies)),
  http.get("*/api/strategy-instances", () => HttpResponse.json(getStrategyInstances)),
  http.post("*/api/strategy-instances", () => HttpResponse.json(postStrategyInstances, { status: 201 })),
  http.get("*/api/strategy-instances/:instance_id", () => HttpResponse.json(getStrategyInstancesInstanceId)),
  http.patch("*/api/strategy-instances/:instance_id", () => HttpResponse.json(patchStrategyInstancesInstanceId)),
  http.delete("*/api/strategy-instances/:instance_id", () => new HttpResponse(null, { status: 204 })),
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
