// 由 `pnpm --dir frontend api:sync` 生成，勿手改。契约源：backend/contracts/openapi.json
export interface paths {
    "/api/backtest-sweeps": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Backtest Sweep */
        post: operations["create_backtest_sweep_api_backtest_sweeps_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Backtests */
        get: operations["list_backtests_api_backtests_get"];
        put?: never;
        /** Create Backtest */
        post: operations["create_backtest_api_backtests_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/ranking": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Backtest Ranking */
        get: operations["get_backtest_ranking_api_backtests_ranking_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Backtest */
        get: operations["get_backtest_api_backtests__run_id__get"];
        put?: never;
        post?: never;
        /** Delete Backtest */
        delete: operations["delete_backtest_api_backtests__run_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/execution": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Execution State */
        get: operations["get_execution_state_api_execution_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/execution/mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Execution Mode */
        put: operations["set_execution_mode_api_execution_mode_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description 存活探针：进程能应答即返回 ok。
         */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/indicators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Indicators */
        get: operations["list_indicators_api_indicators_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/indicators/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Indicator Series */
        get: operations["get_indicator_series_api_indicators_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Search Instruments
         * @description 按代码或产品键做大小写不敏感的包含匹配，可按标的类型过滤。
         */
        get: operations["search_instruments_api_instruments_search_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/{inst_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Instrument
         * @description 单标的详情：交易参数 + 同产品的另一条腿（有行情时才有价差）。
         */
        get: operations["get_instrument_api_instruments__inst_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/{inst_id}/candles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Instrument Candles
         * @description 已落库 K 线的尾部窗口，附带库里真实的可用区间与缺口标记。
         */
        get: operations["get_instrument_candles_api_instruments__inst_id__candles_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/journal": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Journal */
        get: operations["list_journal_api_journal_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Overview */
        get: operations["get_overview_api_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Settings Document */
        get: operations["get_settings_document_api_settings_get"];
        /** Update Settings Document */
        put: operations["update_settings_document_api_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/signals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Signals */
        get: operations["list_signals_api_signals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Strategies */
        get: operations["list_strategies_api_strategies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategy-instances": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Strategy Instances */
        get: operations["list_strategy_instances_api_strategy_instances_get"];
        put?: never;
        /** Create Strategy Instance */
        post: operations["create_strategy_instance_api_strategy_instances_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategy-instances/{instance_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Strategy Instance */
        get: operations["get_strategy_instance_api_strategy_instances__instance_id__get"];
        put?: never;
        post?: never;
        /** Delete Strategy Instance */
        delete: operations["delete_strategy_instance_api_strategy_instances__instance_id__delete"];
        options?: never;
        head?: never;
        /** Update Strategy Instance */
        patch: operations["update_strategy_instance_api_strategy_instances__instance_id__patch"];
        trace?: never;
    };
    "/api/trades/fills": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Fills */
        get: operations["list_fills_api_trades_fills_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/trades/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Orders */
        get: operations["list_orders_api_trades_orders_get"];
        put?: never;
        /** Create Order */
        post: operations["create_order_api_trades_orders_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/trades/orders/{order_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Cancel Order */
        delete: operations["cancel_order_api_trades_orders__order_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/trades/positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Positions */
        get: operations["list_positions_api_trades_positions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/watchlist": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Watchlist
         * @description 按加入顺序返回全部自选条目，以及当前存在的分组名。
         */
        get: operations["list_watchlist_api_watchlist_get"];
        put?: never;
        /**
         * Add Watchlist Item
         * @description 把标的加入自选；标的必须已同步，且已有足够的日线可算行情。
         */
        post: operations["add_watchlist_item_api_watchlist_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/watchlist/{inst_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Watchlist Item
         * @description 删除自选条目及其提醒；分组空了会一并清理。
         */
        delete: operations["delete_watchlist_item_api_watchlist__inst_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Watchlist Item
         * @description 把自选条目换到另一个分组；分组不存在时按需创建。
         */
        patch: operations["update_watchlist_item_api_watchlist__inst_id__patch"];
        trace?: never;
    };
    "/api/watchlist/{inst_id}/alert": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Put Price Alert
         * @description 写入或覆盖价格提醒；标的必须已在自选里。
         */
        put: operations["put_price_alert_api_watchlist__inst_id__alert_put"];
        post?: never;
        /**
         * Delete Price Alert
         * @description 删除价格提醒；没有提醒时按不存在处理。
         */
        delete: operations["delete_price_alert_api_watchlist__inst_id__alert_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/watchlist/{inst_id}/related": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Related Instruments
         * @description 按窗口内日线相关性排序的关联标的；样本不足的候选不出现在结果里。
         */
        get: operations["get_related_instruments_api_watchlist__inst_id__related_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AccountSummary */
        AccountSummary: {
            /** Available */
            available: string;
            /** Currency */
            currency: string;
            /** Equity */
            equity: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
            /** Today Pnl */
            today_pnl: string;
            /** Unrealized Pnl */
            unrealized_pnl: string;
        };
        /** BacktestCosts */
        BacktestCosts: {
            /** Maker Fee Bps */
            maker_fee_bps: string;
            /** Slippage Bps */
            slippage_bps: string;
            /** Spread Bps */
            spread_bps: string;
            /** Taker Fee Bps */
            taker_fee_bps: string;
        };
        /**
         * BacktestDetailResponse
         * @example {
         *       "equity_curve": [
         *         {
         *           "equity": "10000",
         *           "time": "2026-08-01T00:00:00Z"
         *         },
         *         {
         *           "equity": "11240.55",
         *           "time": "2026-11-01T00:00:00Z"
         *         }
         *       ],
         *       "request": {
         *         "bar": "1h",
         *         "costs": {
         *           "maker_fee_bps": "2",
         *           "slippage_bps": "3",
         *           "spread_bps": "2",
         *           "taker_fee_bps": "5"
         *         },
         *         "data_source": "okx",
         *         "end_date": "2026-11-01",
         *         "execution_model": "next_open",
         *         "funding_enabled": true,
         *         "initial_capital": "10000",
         *         "max_position_pct": "0.25",
         *         "position_size": "2000",
         *         "quote_currency": "USDT",
         *         "start_date": "2026-08-01",
         *         "strategy_instance_id": "si_0001",
         *         "targets": {
         *           "inst_ids": [
         *             "XAAPL-USDT"
         *           ],
         *           "mode": "single"
         *         }
         *       },
         *       "run": {
         *         "bar": "1h",
         *         "created_at": "2026-11-10T01:20:00Z",
         *         "data_source": "okx",
         *         "end_date": "2026-11-01",
         *         "finished_at": "2026-11-10T01:21:30Z",
         *         "is_proxy": false,
         *         "metrics": {
         *           "annualized_return_pct": "48.21",
         *           "avg_holding_hours": "18.4",
         *           "final_capital": "11240.55",
         *           "funding_coverage_pct": "100",
         *           "funding_missing_count": 0,
         *           "funding_total": "-12.84",
         *           "initial_capital": "10000",
         *           "max_drawdown_pct": "-6.12",
         *           "max_single_loss": "-158.20",
         *           "max_single_win": "312.40",
         *           "payoff_ratio": "1.72",
         *           "profit_factor": "1.95",
         *           "sharpe": "1.31",
         *           "total_return_pct": "12.4055",
         *           "trade_count": 37,
         *           "win_rate": "0.54"
         *         },
         *         "run_id": "bt_0001",
         *         "start_date": "2026-08-01",
         *         "status": "succeeded",
         *         "strategy_instance_id": "si_0001",
         *         "symbol_count": 1
         *       },
         *       "trades": [
         *         {
         *           "entry_price": "228.10",
         *           "entry_time": "2026-08-04T14:00:00Z",
         *           "exit_price": "232.44",
         *           "exit_time": "2026-08-05T06:00:00Z",
         *           "fee": "1.98",
         *           "funding": "0",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "pnl": "35.24",
         *           "qty": "8.63",
         *           "reason": "MA20 下穿 MA60",
         *           "side": "buy",
         *           "trade_id": "tr_0001"
         *         }
         *       ]
         *     }
         */
        BacktestDetailResponse: {
            /** Equity Curve */
            equity_curve: components["schemas"]["EquityPoint"][];
            request: components["schemas"]["BacktestRequest"];
            run: components["schemas"]["BacktestRunSummary"];
            /** Trades */
            trades: components["schemas"]["BacktestTrade"][];
        };
        /** BacktestMetrics */
        BacktestMetrics: {
            /** Annualized Return Pct */
            annualized_return_pct?: string | null;
            /** Avg Holding Hours */
            avg_holding_hours: string;
            /** Final Capital */
            final_capital: string;
            /** Funding Coverage Pct */
            funding_coverage_pct?: string | null;
            /** Funding Missing Count */
            funding_missing_count?: number | null;
            /** Funding Total */
            funding_total?: string | null;
            /** Initial Capital */
            initial_capital: string;
            /** Max Drawdown Pct */
            max_drawdown_pct: string;
            /** Max Single Loss */
            max_single_loss: string;
            /** Max Single Win */
            max_single_win: string;
            /** Payoff Ratio */
            payoff_ratio: string;
            /** Profit Factor */
            profit_factor: string;
            /** Sharpe */
            sharpe: string;
            /** Total Return Pct */
            total_return_pct: string;
            /** Trade Count */
            trade_count: number;
            /** Win Rate */
            win_rate: string;
        };
        /**
         * BacktestRankingResponse
         * @example {
         *       "data_source": "okx",
         *       "items": [
         *         {
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "max_drawdown_pct": "-6.12",
         *           "profit_factor": "1.95",
         *           "sharpe": "1.31",
         *           "total_return_pct": "12.4055",
         *           "trade_count": 37
         *         }
         *       ],
         *       "metric": "total_return_pct"
         *     }
         */
        BacktestRankingResponse: {
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /** Items */
            items: components["schemas"]["BacktestRankingRow"][];
            /**
             * Metric
             * @enum {string}
             */
            metric: "total_return_pct" | "max_drawdown_pct" | "sharpe" | "profit_factor";
        };
        /** BacktestRankingRow */
        BacktestRankingRow: {
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Max Drawdown Pct */
            max_drawdown_pct: string;
            /** Profit Factor */
            profit_factor: string;
            /** Sharpe */
            sharpe: string;
            /** Total Return Pct */
            total_return_pct: string;
            /** Trade Count */
            trade_count: number;
        };
        /**
         * BacktestRequest
         * @description 一次回测的全部可复现输入。结果必须能按这份配置重放。
         */
        BacktestRequest: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            costs: components["schemas"]["BacktestCosts"];
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /**
             * End Date
             * Format: date
             */
            end_date: string;
            /**
             * Execution Model
             * @enum {string}
             */
            execution_model: "next_open" | "next_close";
            /**
             * Funding Enabled
             * @default true
             */
            funding_enabled: boolean;
            /** Initial Capital */
            initial_capital: string;
            /** Max Position Pct */
            max_position_pct: string;
            /** Position Size */
            position_size: string;
            /** Quote Currency */
            quote_currency: string;
            /**
             * Start Date
             * Format: date
             */
            start_date: string;
            /** Strategy Instance Id */
            strategy_instance_id: string;
            targets: components["schemas"]["BacktestTargets"];
        };
        /**
         * BacktestRunListResponse
         * @example {
         *       "data_source": "okx",
         *       "items": [
         *         {
         *           "bar": "1h",
         *           "created_at": "2026-11-10T01:20:00Z",
         *           "data_source": "okx",
         *           "end_date": "2026-11-01",
         *           "finished_at": "2026-11-10T01:21:30Z",
         *           "is_proxy": false,
         *           "metrics": {
         *             "annualized_return_pct": "48.21",
         *             "avg_holding_hours": "18.4",
         *             "final_capital": "11240.55",
         *             "funding_coverage_pct": "100",
         *             "funding_missing_count": 0,
         *             "funding_total": "-12.84",
         *             "initial_capital": "10000",
         *             "max_drawdown_pct": "-6.12",
         *             "max_single_loss": "-158.20",
         *             "max_single_win": "312.40",
         *             "payoff_ratio": "1.72",
         *             "profit_factor": "1.95",
         *             "sharpe": "1.31",
         *             "total_return_pct": "12.4055",
         *             "trade_count": 37,
         *             "win_rate": "0.54"
         *           },
         *           "run_id": "bt_0001",
         *           "start_date": "2026-08-01",
         *           "status": "succeeded",
         *           "strategy_instance_id": "si_0001",
         *           "symbol_count": 1
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        BacktestRunListResponse: {
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /** Items */
            items: components["schemas"]["BacktestRunSummary"][];
            /** Total */
            total: number;
        };
        /**
         * BacktestRunSummary
         * @example {
         *       "bar": "1h",
         *       "created_at": "2026-11-10T01:20:00Z",
         *       "data_source": "okx",
         *       "end_date": "2026-11-01",
         *       "finished_at": "2026-11-10T01:21:30Z",
         *       "is_proxy": false,
         *       "metrics": {
         *         "annualized_return_pct": "48.21",
         *         "avg_holding_hours": "18.4",
         *         "final_capital": "11240.55",
         *         "funding_coverage_pct": "100",
         *         "funding_missing_count": 0,
         *         "funding_total": "-12.84",
         *         "initial_capital": "10000",
         *         "max_drawdown_pct": "-6.12",
         *         "max_single_loss": "-158.20",
         *         "max_single_win": "312.40",
         *         "payoff_ratio": "1.72",
         *         "profit_factor": "1.95",
         *         "sharpe": "1.31",
         *         "total_return_pct": "12.4055",
         *         "trade_count": 37,
         *         "win_rate": "0.54"
         *       },
         *       "run_id": "bt_0001",
         *       "start_date": "2026-08-01",
         *       "status": "succeeded",
         *       "strategy_instance_id": "si_0001",
         *       "symbol_count": 1
         *     }
         */
        BacktestRunSummary: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Created At */
            created_at: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /**
             * End Date
             * Format: date
             */
            end_date: string;
            /** Error Message */
            error_message?: string | null;
            /** Finished At */
            finished_at?: string | null;
            /** Is Proxy */
            is_proxy: boolean;
            metrics?: components["schemas"]["BacktestMetrics"] | null;
            /** Run Id */
            run_id: string;
            /**
             * Start Date
             * Format: date
             */
            start_date: string;
            /**
             * Status
             * @enum {string}
             */
            status: "queued" | "running" | "succeeded" | "failed";
            /** Strategy Instance Id */
            strategy_instance_id: string;
            /** Symbol Count */
            symbol_count: number;
        };
        /** BacktestSettings */
        BacktestSettings: {
            /**
             * Default Bar
             * @enum {string}
             */
            default_bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Default Initial Capital */
            default_initial_capital: string;
            /** Funding Enabled */
            funding_enabled: boolean;
        };
        /** BacktestSweepCombo */
        BacktestSweepCombo: {
            /** Error Message */
            error_message?: string | null;
            metrics?: components["schemas"]["BacktestMetrics"] | null;
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
        };
        /**
         * BacktestSweepRequest
         * @description 参数组合扫描：网格 + 训练/验证/样本外切分，防止把最优历史参数当结论。
         */
        BacktestSweepRequest: {
            /** Param Grid */
            param_grid: {
                [key: string]: (number | string | boolean)[];
            };
            request: components["schemas"]["BacktestRequest"];
            /** Splits */
            splits: components["schemas"]["TimeSplit"][];
        };
        /**
         * BacktestSweepResponse
         * @example {
         *       "combos": [
         *         {
         *           "params": {
         *             "fast": 10,
         *             "slow": 40
         *           }
         *         }
         *       ],
         *       "created_at": "2026-11-10T01:30:00Z",
         *       "data_source": "okx",
         *       "status": "succeeded",
         *       "sweep_id": "sw_0001"
         *     }
         */
        BacktestSweepResponse: {
            /** Combos */
            combos: components["schemas"]["BacktestSweepCombo"][];
            /** Created At */
            created_at: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /**
             * Status
             * @enum {string}
             */
            status: "queued" | "running" | "succeeded" | "failed";
            /** Sweep Id */
            sweep_id: string;
        };
        /**
         * BacktestTargets
         * @description 标的范围：单标的 / 手选多个 / 自选分组 / Watchlist 全部 / 全市场。
         */
        BacktestTargets: {
            /** Group */
            group?: string | null;
            /** Inst Ids */
            inst_ids?: string[];
            /**
             * Mode
             * @enum {string}
             */
            mode: "single" | "list" | "watchlist" | "group" | "all";
        };
        /** BacktestTrade */
        BacktestTrade: {
            /** Entry Price */
            entry_price: string;
            /** Entry Time */
            entry_time: string;
            /** Exit Price */
            exit_price: string;
            /** Exit Time */
            exit_time: string;
            /** Fee */
            fee: string;
            /** Funding */
            funding: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Pnl */
            pnl: string;
            /** Qty */
            qty: string;
            /** Reason */
            reason: string;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
            /** Trade Id */
            trade_id: string;
        };
        /**
         * Candle
         * @description 一根 K 线。`is_closed=false` 表示未完成，`data_source` 区分真实/代理。
         */
        Candle: {
            /** Close */
            close: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /** High */
            high: string;
            /** Is Closed */
            is_closed: boolean;
            /** Low */
            low: string;
            /** Open */
            open: string;
            /** Open Time */
            open_time: string;
            /** Volume */
            volume: string;
        };
        /**
         * CandleSeriesResponse
         * @description K 线窗口。数据不足时 `available_from` 如实反映真实起点，禁止补造。
         * @example {
         *       "available_from": "2026-11-10T05:00:00Z",
         *       "available_to": "2026-11-10T07:00:00Z",
         *       "bar": "1h",
         *       "candles": [
         *         {
         *           "close": "231.42",
         *           "data_source": "okx",
         *           "high": "232.10",
         *           "is_closed": true,
         *           "low": "229.44",
         *           "open": "229.80",
         *           "open_time": "2026-11-10T07:00:00Z",
         *           "volume": "1520.335"
         *         }
         *       ],
         *       "data_source": "okx",
         *       "has_gap": false,
         *       "inst_id": "XAAPL-USDT"
         *     }
         */
        CandleSeriesResponse: {
            /** Available From */
            available_from?: string | null;
            /** Available To */
            available_to?: string | null;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Candles */
            candles: components["schemas"]["Candle"][];
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "us_equity_proxy";
            /**
             * Has Gap
             * @default false
             */
            has_gap: boolean;
            /** Inst Id */
            inst_id: string;
        };
        /** CostSettings */
        CostSettings: {
            /** Maker Fee Bps */
            maker_fee_bps: string;
            /** Slippage Bps */
            slippage_bps: string;
            /** Spread Bps */
            spread_bps: string;
            /** Taker Fee Bps */
            taker_fee_bps: string;
        };
        /** DataSettings */
        DataSettings: {
            /** Proxy Configured */
            proxy_configured: boolean;
            /** Proxy Enabled */
            proxy_enabled: boolean;
        };
        /** EquityPoint */
        EquityPoint: {
            /** Equity */
            equity: string;
            /** Time */
            time: string;
        };
        /** ExchangeSettings */
        ExchangeSettings: {
            /** Api Configured */
            api_configured: boolean;
            /** Demo Trading */
            demo_trading: boolean;
        };
        /** ExecutionModeRequest */
        ExecutionModeRequest: {
            /**
             * Acknowledge Risk
             * @default false
             */
            acknowledge_risk: boolean;
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
        };
        /** ExecutionSettings */
        ExecutionSettings: {
            /** Auto Trading Enabled */
            auto_trading_enabled: boolean;
            /** Emergency Stop */
            emergency_stop: boolean;
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
        };
        /**
         * ExecutionStateResponse
         * @example {
         *       "auto_trading_enabled": false,
         *       "emergency_stop": false,
         *       "mode": "paper"
         *     }
         */
        ExecutionStateResponse: {
            /** Auto Trading Enabled */
            auto_trading_enabled: boolean;
            /** Emergency Stop */
            emergency_stop: boolean;
            /** Live Acknowledged At */
            live_acknowledged_at?: string | null;
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
        };
        /** ExposureSummary */
        ExposureSummary: {
            /** Gross Exposure */
            gross_exposure: string;
            /** Margin Used Pct */
            margin_used_pct: string;
            /** Net Exposure */
            net_exposure: string;
        };
        /** Fill */
        Fill: {
            /** Fee */
            fee: string;
            /** Fee Currency */
            fee_currency: string;
            /** Fill Id */
            fill_id: string;
            /** Filled At */
            filled_at: string;
            /** Inst Id */
            inst_id: string;
            /** Order Id */
            order_id: string;
            /** Price */
            price: string;
            /** Qty */
            qty: string;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
        };
        /**
         * FillListResponse
         * @example {
         *       "items": [
         *         {
         *           "fee": "0.98",
         *           "fee_currency": "USDT",
         *           "fill_id": "fill_0001",
         *           "filled_at": "2026-11-09T14:00:02Z",
         *           "inst_id": "XAAPL-USDT",
         *           "order_id": "ord_0001",
         *           "price": "228.10",
         *           "qty": "8.63",
         *           "side": "buy"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        FillListResponse: {
            /** Items */
            items: components["schemas"]["Fill"][];
            /** Total */
            total: number;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * HealthResponse
         * @description 稳定的探针响应结构，前端与运维脚本按字段读取。
         * @example {
         *       "env": "dev",
         *       "status": "ok",
         *       "version": "0.2.0"
         *     }
         */
        HealthResponse: {
            /** Env */
            env: string;
            /**
             * Status
             * @constant
             */
            status: "ok";
            /** Version */
            version: string;
        };
        /**
         * IndicatorCatalogResponse
         * @example {
         *       "items": [
         *         {
         *           "min_bars": 15,
         *           "name": "rsi",
         *           "outputs": [
         *             "rsi"
         *           ],
         *           "params": [
         *             {
         *               "default": 14,
         *               "kind": "int",
         *               "maximum": 200,
         *               "minimum": 2,
         *               "name": "period",
         *               "title": "周期"
         *             }
         *           ],
         *           "summary": "相对强弱指标: 衡量近期涨跌幅度之比。",
         *           "title": "RSI"
         *         }
         *       ]
         *     }
         */
        IndicatorCatalogResponse: {
            /** Items */
            items: components["schemas"]["IndicatorDefinition"][];
        };
        /**
         * IndicatorDefinition
         * @description 单个指标的元数据：参数、输出字段、最小数据长度。
         */
        IndicatorDefinition: {
            /** Min Bars */
            min_bars: number;
            /** Name */
            name: string;
            /** Outputs */
            outputs: string[];
            /** Params */
            params: components["schemas"]["ParamSpec"][];
            /** Summary */
            summary: string;
            /** Title */
            title: string;
        };
        /** IndicatorPoint */
        IndicatorPoint: {
            /** Time */
            time: string;
            /** Values */
            values: {
                [key: string]: string | null;
            };
        };
        /** IndicatorSeries */
        IndicatorSeries: {
            /** Name */
            name: string;
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
            /** Points */
            points: components["schemas"]["IndicatorPoint"][];
        };
        /**
         * IndicatorSeriesResponse
         * @example {
         *       "bar": "1h",
         *       "inst_id": "XAAPL-USDT",
         *       "inst_type": "SPOT",
         *       "series": [
         *         {
         *           "name": "rsi",
         *           "params": {
         *             "period": 14
         *           },
         *           "points": [
         *             {
         *               "time": "2026-11-10T07:00:00Z",
         *               "values": {
         *                 "rsi": "58.21"
         *               }
         *             }
         *           ]
         *         }
         *       ]
         *     }
         */
        IndicatorSeriesResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Series */
            series: components["schemas"]["IndicatorSeries"][];
        };
        /**
         * InstrumentDetailResponse
         * @example {
         *       "instrument": {
         *         "asset_type": "tokenized_equity",
         *         "base_currency": "XAAPL",
         *         "inst_id": "XAAPL-USDT",
         *         "inst_type": "SPOT",
         *         "listing_time": "2026-07-01T00:00:00Z",
         *         "lot_size": "0.001",
         *         "min_order_size": "0.001",
         *         "product_key": "AAPL",
         *         "quote_currency": "USDT",
         *         "tick_size": "0.01",
         *         "trading_status": "live"
         *       },
         *       "latest_signal": {
         *         "action": "BUY",
         *         "bar": "1h",
         *         "generated_at": "2026-11-10T07:00:00Z",
         *         "inst_id": "XAAPL-USDT",
         *         "inst_type": "SPOT",
         *         "price": "231.42",
         *         "reason": "MA20 上穿 MA60",
         *         "signal_id": "sig_0001",
         *         "strategy_instance_id": "si_0001",
         *         "target_weight": "0.25"
         *       },
         *       "siblings": [
         *         {
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "inst_type": "SWAP",
         *           "last_price": "231.55",
         *           "price_spread_pct": "0.06"
         *         }
         *       ]
         *     }
         */
        InstrumentDetailResponse: {
            instrument: components["schemas"]["InstrumentInfo"];
            latest_signal?: components["schemas"]["Signal"] | null;
            /** Siblings */
            siblings: components["schemas"]["SiblingQuote"][];
        };
        /**
         * InstrumentInfo
         * @description 标的静态元数据。SWAP 专属字段对 SPOT 为 null。
         */
        InstrumentInfo: {
            /**
             * Asset Type
             * @enum {string}
             */
            asset_type: "tokenized_equity" | "crypto" | "commodity_token" | "unknown";
            /** Base Currency */
            base_currency: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Listing Time */
            listing_time?: string | null;
            /** Lot Size */
            lot_size?: string | null;
            /** Max Leverage */
            max_leverage?: string | null;
            /** Min Order Size */
            min_order_size?: string | null;
            /** Product Key */
            product_key: string;
            /** Quote Currency */
            quote_currency: string;
            /** Tick Size */
            tick_size?: string | null;
            /**
             * Trading Status
             * @default unknown
             * @enum {string}
             */
            trading_status: "live" | "suspend" | "preopen" | "test" | "expired" | "unknown";
        };
        /**
         * InstrumentRef
         * @description 标的的最小可引用形状（列表、搜索结果用）。
         */
        InstrumentRef: {
            /**
             * Asset Type
             * @enum {string}
             */
            asset_type: "tokenized_equity" | "crypto" | "commodity_token" | "unknown";
            /** Base Currency */
            base_currency: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Product Key */
            product_key: string;
            /** Quote Currency */
            quote_currency: string;
        };
        /**
         * InstrumentSearchResponse
         * @example {
         *       "items": [
         *         {
         *           "asset_type": "tokenized_equity",
         *           "base_currency": "XAAPL",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "product_key": "AAPL",
         *           "quote_currency": "USDT"
         *         },
         *         {
         *           "asset_type": "tokenized_equity",
         *           "base_currency": "AAPL",
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "inst_type": "SWAP",
         *           "product_key": "AAPL",
         *           "quote_currency": "USDT"
         *         }
         *       ]
         *     }
         */
        InstrumentSearchResponse: {
            /** Items */
            items: components["schemas"]["InstrumentRef"][];
        };
        /** JournalEntry */
        JournalEntry: {
            /**
             * Category
             * @enum {string}
             */
            category: "signal" | "order" | "fill" | "mode_change" | "risk_block" | "settings";
            /** Created At */
            created_at: string;
            /** Entry Id */
            entry_id: string;
            /** Inst Id */
            inst_id?: string | null;
            /** Message */
            message: string;
        };
        /**
         * JournalListResponse
         * @example {
         *       "items": [
         *         {
         *           "category": "mode_change",
         *           "created_at": "2026-11-10T06:10:00Z",
         *           "entry_id": "jrn_0001",
         *           "message": "执行模式 paper -> live, 已二次确认风险"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        JournalListResponse: {
            /** Items */
            items: components["schemas"]["JournalEntry"][];
            /** Total */
            total: number;
        };
        /**
         * Order
         * @example {
         *       "avg_fill_price": "228.10",
         *       "client_order_id": "cli_9f2a",
         *       "created_at": "2026-11-09T13:59:40Z",
         *       "filled_qty": "8.63",
         *       "inst_id": "XAAPL-USDT",
         *       "inst_type": "SPOT",
         *       "mode": "paper",
         *       "order_id": "ord_0001",
         *       "order_type": "limit",
         *       "price": "228.10",
         *       "qty": "8.63",
         *       "reduce_only": false,
         *       "side": "buy",
         *       "status": "filled",
         *       "strategy_instance_id": "si_0001",
         *       "updated_at": "2026-11-09T14:00:02Z"
         *     }
         */
        Order: {
            /** Avg Fill Price */
            avg_fill_price?: string | null;
            /** Client Order Id */
            client_order_id: string;
            /** Created At */
            created_at: string;
            /** Filled Qty */
            filled_qty: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
            /** Order Id */
            order_id: string;
            /**
             * Order Type
             * @enum {string}
             */
            order_type: "market" | "limit";
            /** Price */
            price?: string | null;
            /** Qty */
            qty: string;
            /** Reduce Only */
            reduce_only: boolean;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "open" | "partially_filled" | "filled" | "cancelled" | "rejected";
            /** Strategy Instance Id */
            strategy_instance_id?: string | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * OrderCreateRequest
         * @description 手动确认下单。`client_order_id` 留空时由服务端生成，用于幂等。
         */
        OrderCreateRequest: {
            /**
             * Acknowledge Risk
             * @default false
             */
            acknowledge_risk: boolean;
            /** Client Order Id */
            client_order_id?: string | null;
            /** Inst Id */
            inst_id: string;
            /**
             * Order Type
             * @enum {string}
             */
            order_type: "market" | "limit";
            /** Price */
            price?: string | null;
            /** Qty */
            qty: string;
            /**
             * Reduce Only
             * @default false
             */
            reduce_only: boolean;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
        };
        /**
         * OrderListResponse
         * @example {
         *       "items": [
         *         {
         *           "avg_fill_price": "228.10",
         *           "client_order_id": "cli_9f2a",
         *           "created_at": "2026-11-09T13:59:40Z",
         *           "filled_qty": "8.63",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "mode": "paper",
         *           "order_id": "ord_0001",
         *           "order_type": "limit",
         *           "price": "228.10",
         *           "qty": "8.63",
         *           "reduce_only": false,
         *           "side": "buy",
         *           "status": "filled",
         *           "strategy_instance_id": "si_0001",
         *           "updated_at": "2026-11-09T14:00:02Z"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        OrderListResponse: {
            /** Items */
            items: components["schemas"]["Order"][];
            /** Total */
            total: number;
        };
        /**
         * OverviewResponse
         * @example {
         *       "account": {
         *         "available": "8160.00",
         *         "currency": "USDT",
         *         "equity": "10240.55",
         *         "mode": "paper",
         *         "today_pnl": "-12.30",
         *         "unrealized_pnl": "28.64"
         *       },
         *       "active_strategies": [
         *         {
         *           "instance_id": "si_0001",
         *           "latest_signal_at": "2026-11-10T07:00:00Z",
         *           "name": "AAPL 均线趋势",
         *           "status": "enabled",
         *           "strategy_id": "ma_cross"
         *         }
         *       ],
         *       "exposure": {
         *         "gross_exposure": "1997.15",
         *         "margin_used_pct": "19.5",
         *         "net_exposure": "1997.15"
         *       },
         *       "generated_at": "2026-11-10T08:00:00Z",
         *       "positions": [
         *         {
         *           "avg_entry_price": "228.10",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "leverage": "1",
         *           "mark_price": "231.42",
         *           "mode": "paper",
         *           "notional": "1997.15",
         *           "opened_at": "2026-11-09T14:00:00Z",
         *           "product_key": "AAPL",
         *           "qty": "8.63",
         *           "side": "long",
         *           "strategy_instance_id": "si_0001",
         *           "unrealized_pnl": "28.64"
         *         }
         *       ],
         *       "recent_signals": [
         *         {
         *           "action": "BUY",
         *           "bar": "1h",
         *           "generated_at": "2026-11-10T07:00:00Z",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "price": "231.42",
         *           "reason": "MA20 上穿 MA60",
         *           "signal_id": "sig_0001",
         *           "strategy_instance_id": "si_0001",
         *           "target_weight": "0.25"
         *         }
         *       ],
         *       "watchlist_highlights": [
         *         {
         *           "change_pct_24h": "1.86",
         *           "inst_id": "XAAPL-USDT",
         *           "last_price": "231.42",
         *           "product_key": "AAPL"
         *         }
         *       ]
         *     }
         */
        OverviewResponse: {
            account: components["schemas"]["AccountSummary"];
            /** Active Strategies */
            active_strategies: components["schemas"]["StrategyBrief"][];
            exposure: components["schemas"]["ExposureSummary"];
            /** Generated At */
            generated_at: string;
            /** Positions */
            positions: components["schemas"]["Position"][];
            /** Recent Signals */
            recent_signals: components["schemas"]["Signal"][];
            /** Watchlist Highlights */
            watchlist_highlights: components["schemas"]["WatchlistBrief"][];
        };
        /**
         * ParamSpec
         * @description 指标或策略的可配置参数定义。
         */
        ParamSpec: {
            /** Default */
            default: number | string | boolean;
            /**
             * Kind
             * @enum {string}
             */
            kind: "int" | "float" | "bool" | "string";
            /** Maximum */
            maximum?: number | null;
            /** Minimum */
            minimum?: number | null;
            /** Name */
            name: string;
            /** Title */
            title: string;
        };
        /** Position */
        Position: {
            /** Avg Entry Price */
            avg_entry_price: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Leverage */
            leverage: string;
            /** Liquidation Price */
            liquidation_price?: string | null;
            /** Mark Price */
            mark_price: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
            /** Notional */
            notional: string;
            /** Opened At */
            opened_at: string;
            /** Product Key */
            product_key: string;
            /** Qty */
            qty: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /** Strategy Instance Id */
            strategy_instance_id?: string | null;
            /** Unrealized Pnl */
            unrealized_pnl: string;
        };
        /**
         * PositionListResponse
         * @example {
         *       "items": [
         *         {
         *           "avg_entry_price": "228.10",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "leverage": "1",
         *           "mark_price": "231.42",
         *           "mode": "paper",
         *           "notional": "1997.15",
         *           "opened_at": "2026-11-09T14:00:00Z",
         *           "product_key": "AAPL",
         *           "qty": "8.63",
         *           "side": "long",
         *           "strategy_instance_id": "si_0001",
         *           "unrealized_pnl": "28.64"
         *         }
         *       ],
         *       "mode": "paper"
         *     }
         */
        PositionListResponse: {
            /** Items */
            items: components["schemas"]["Position"][];
            /**
             * Mode
             * @enum {string}
             */
            mode: "manual" | "paper" | "live";
        };
        /**
         * PriceAlert
         * @example {
         *       "direction": "above",
         *       "enabled": true,
         *       "inst_id": "XAAPL-USDT",
         *       "price": "235.00"
         *     }
         */
        PriceAlert: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "above" | "below";
            /** Enabled */
            enabled: boolean;
            /** Inst Id */
            inst_id: string;
            /** Price */
            price: string;
            /** Triggered At */
            triggered_at?: string | null;
        };
        /** PriceAlertRequest */
        PriceAlertRequest: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "above" | "below";
            /**
             * Enabled
             * @default true
             */
            enabled: boolean;
            /** Price */
            price: string;
        };
        /** RelatedInstrument */
        RelatedInstrument: {
            /**
             * Asset Type
             * @enum {string}
             */
            asset_type: "tokenized_equity" | "crypto" | "commodity_token" | "unknown";
            /** Correlation */
            correlation: string;
            /** Inst Id */
            inst_id: string;
            /** Product Key */
            product_key: string;
            /** Window Days */
            window_days: number;
        };
        /**
         * RelatedInstrumentsResponse
         * @example {
         *       "inst_id": "XAAPL-USDT",
         *       "items": [
         *         {
         *           "asset_type": "tokenized_equity",
         *           "correlation": "0.87",
         *           "inst_id": "XQQQ-USDT",
         *           "product_key": "QQQ",
         *           "window_days": 30
         *         }
         *       ],
         *       "window_days": 30
         *     }
         */
        RelatedInstrumentsResponse: {
            /** Inst Id */
            inst_id: string;
            /** Items */
            items: components["schemas"]["RelatedInstrument"][];
            /** Window Days */
            window_days: number;
        };
        /**
         * RiskSettings
         * @description 风控限额。`max_leverage` 的硬上限（10）不因配置抬高（decisions.md L1）。
         */
        RiskSettings: {
            /** Liquidation Buffer Pct */
            liquidation_buffer_pct: string;
            /** Max Daily Loss */
            max_daily_loss: string;
            /** Max Leverage */
            max_leverage: string;
            /** Max Order Notional */
            max_order_notional: string;
            /** Max Position Notional */
            max_position_notional: string;
            /** Max Positions */
            max_positions: number;
            /** Max Total Notional */
            max_total_notional: string;
            /** Stop Loss Mandatory */
            stop_loss_mandatory: boolean;
        };
        /**
         * SettingsResponse
         * @example {
         *       "backtest": {
         *         "default_bar": "1h",
         *         "default_initial_capital": "10000",
         *         "funding_enabled": true
         *       },
         *       "costs": {
         *         "maker_fee_bps": "2",
         *         "slippage_bps": "3",
         *         "spread_bps": "2",
         *         "taker_fee_bps": "5"
         *       },
         *       "data": {
         *         "proxy_configured": false,
         *         "proxy_enabled": false
         *       },
         *       "exchange": {
         *         "api_configured": false,
         *         "demo_trading": true
         *       },
         *       "execution": {
         *         "auto_trading_enabled": false,
         *         "emergency_stop": false,
         *         "mode": "paper"
         *       },
         *       "risk": {
         *         "liquidation_buffer_pct": "10",
         *         "max_daily_loss": "300",
         *         "max_leverage": "3",
         *         "max_order_notional": "1000",
         *         "max_position_notional": "3000",
         *         "max_positions": 5,
         *         "max_total_notional": "10000",
         *         "stop_loss_mandatory": true
         *       },
         *       "updated_at": "2026-11-10T06:10:00Z"
         *     }
         */
        SettingsResponse: {
            backtest: components["schemas"]["BacktestSettings"];
            costs: components["schemas"]["CostSettings"];
            data: components["schemas"]["DataSettings"];
            exchange: components["schemas"]["ExchangeSettings"];
            execution: components["schemas"]["ExecutionSettings"];
            risk: components["schemas"]["RiskSettings"];
            /** Updated At */
            updated_at: string;
        };
        /**
         * SettingsUpdateRequest
         * @description 分组级部分更新；交易所凭据不在可写范围。
         */
        SettingsUpdateRequest: {
            backtest?: components["schemas"]["BacktestSettings"] | null;
            costs?: components["schemas"]["CostSettings"] | null;
            data?: components["schemas"]["DataSettings"] | null;
            execution?: components["schemas"]["ExecutionSettings"] | null;
            risk?: components["schemas"]["RiskSettings"] | null;
        };
        /**
         * SiblingQuote
         * @description 同一 `product_key` 的另一形态报价。两形态不等价，界面必须同时展示价差。
         */
        SiblingQuote: {
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Last Price */
            last_price: string;
            /** Price Spread Pct */
            price_spread_pct: string;
        };
        /**
         * Signal
         * @description 策略输出的标准化交易信号，策略本身不产生订单。
         */
        Signal: {
            /**
             * Action
             * @enum {string}
             */
            action: "BUY" | "SELL" | "HOLD";
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Generated At */
            generated_at: string;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Price */
            price: string;
            /** Reason */
            reason: string;
            /** Signal Id */
            signal_id: string;
            /** Strategy Instance Id */
            strategy_instance_id: string;
            /** Target Weight */
            target_weight?: string | null;
        };
        /**
         * SignalListResponse
         * @example {
         *       "items": [
         *         {
         *           "action": "BUY",
         *           "bar": "1h",
         *           "generated_at": "2026-11-10T07:00:00Z",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "price": "231.42",
         *           "reason": "MA20 上穿 MA60",
         *           "signal_id": "sig_0001",
         *           "strategy_instance_id": "si_0001",
         *           "target_weight": "0.25"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        SignalListResponse: {
            /** Items */
            items: components["schemas"]["Signal"][];
            /** Total */
            total: number;
        };
        /** StrategyBrief */
        StrategyBrief: {
            /** Instance Id */
            instance_id: string;
            /** Latest Signal At */
            latest_signal_at?: string | null;
            /** Name */
            name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "enabled" | "disabled";
            /** Strategy Id */
            strategy_id: string;
        };
        /**
         * StrategyCatalogResponse
         * @example {
         *       "items": [
         *         {
         *           "emitted_actions": [
         *             "BUY",
         *             "SELL",
         *             "HOLD"
         *           ],
         *           "name": "MA Cross",
         *           "params": [
         *             {
         *               "default": 20,
         *               "kind": "int",
         *               "maximum": 200,
         *               "minimum": 2,
         *               "name": "fast",
         *               "title": "快线周期"
         *             },
         *             {
         *               "default": 60,
         *               "kind": "int",
         *               "maximum": 500,
         *               "minimum": 3,
         *               "name": "slow",
         *               "title": "慢线周期"
         *             }
         *           ],
         *           "required_bars": [
         *             "1h",
         *             "4h",
         *             "1d"
         *           ],
         *           "required_indicators": [
         *             "sma"
         *           ],
         *           "strategy_id": "ma_cross",
         *           "summary": "快慢均线交叉产生多空信号。",
         *           "version": "1.0.0"
         *         }
         *       ]
         *     }
         */
        StrategyCatalogResponse: {
            /** Items */
            items: components["schemas"]["StrategyDefinition"][];
        };
        /**
         * StrategyDefinition
         * @description 策略模板：一个模板可派生多个独立配置的实例。
         */
        StrategyDefinition: {
            /** Emitted Actions */
            emitted_actions: ("BUY" | "SELL" | "HOLD")[];
            /** Name */
            name: string;
            /** Params */
            params: components["schemas"]["ParamSpec"][];
            /** Required Bars */
            required_bars: ("1m" | "5m" | "15m" | "1h" | "4h" | "1d")[];
            /** Required Indicators */
            required_indicators: string[];
            /** Strategy Id */
            strategy_id: string;
            /** Summary */
            summary: string;
            /** Version */
            version: string;
        };
        /**
         * StrategyInstance
         * @example {
         *       "bar": "1h",
         *       "created_at": "2026-11-08T02:15:00Z",
         *       "execution_mode": "paper",
         *       "inst_ids": [
         *         "XAAPL-USDT"
         *       ],
         *       "instance_id": "si_0001",
         *       "latest_signal_at": "2026-11-10T07:00:00Z",
         *       "name": "AAPL 均线趋势",
         *       "params": {
         *         "fast": 20,
         *         "slow": 60
         *       },
         *       "status": "enabled",
         *       "strategy_id": "ma_cross",
         *       "strategy_version": "1.0.0",
         *       "updated_at": "2026-11-10T07:00:00Z"
         *     }
         */
        StrategyInstance: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Created At */
            created_at: string;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode: "manual" | "paper" | "live";
            /** Inst Ids */
            inst_ids: string[];
            /** Instance Id */
            instance_id: string;
            /** Latest Signal At */
            latest_signal_at?: string | null;
            /** Name */
            name: string;
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "enabled" | "disabled";
            /** Strategy Id */
            strategy_id: string;
            /** Strategy Version */
            strategy_version: string;
            /** Updated At */
            updated_at: string;
        };
        /** StrategyInstanceCreateRequest */
        StrategyInstanceCreateRequest: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Inst Ids */
            inst_ids: string[];
            /** Name */
            name: string;
            /** Params */
            params?: {
                [key: string]: number | string | boolean;
            };
            /** Strategy Id */
            strategy_id: string;
        };
        /**
         * StrategyInstanceListResponse
         * @example {
         *       "items": [
         *         {
         *           "bar": "1h",
         *           "created_at": "2026-11-08T02:15:00Z",
         *           "execution_mode": "paper",
         *           "inst_ids": [
         *             "XAAPL-USDT"
         *           ],
         *           "instance_id": "si_0001",
         *           "latest_signal_at": "2026-11-10T07:00:00Z",
         *           "name": "AAPL 均线趋势",
         *           "params": {
         *             "fast": 20,
         *             "slow": 60
         *           },
         *           "status": "enabled",
         *           "strategy_id": "ma_cross",
         *           "strategy_version": "1.0.0",
         *           "updated_at": "2026-11-10T07:00:00Z"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        StrategyInstanceListResponse: {
            /** Items */
            items: components["schemas"]["StrategyInstance"][];
            /** Total */
            total: number;
        };
        /**
         * StrategyInstanceUpdateRequest
         * @description PATCH 语义：只落显式提交的字段。
         */
        StrategyInstanceUpdateRequest: {
            /** Inst Ids */
            inst_ids?: string[] | null;
            /** Name */
            name?: string | null;
            /** Params */
            params?: {
                [key: string]: number | string | boolean;
            } | null;
            /** Status */
            status?: ("draft" | "enabled" | "disabled") | null;
        };
        /** TimeSplit */
        TimeSplit: {
            /**
             * End Date
             * Format: date
             */
            end_date: string;
            /**
             * Name
             * @enum {string}
             */
            name: "train" | "validation" | "test";
            /**
             * Start Date
             * Format: date
             */
            start_date: string;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WatchlistAddRequest */
        WatchlistAddRequest: {
            /**
             * Group
             * @default 默认
             */
            group: string;
            /** Inst Id */
            inst_id: string;
        };
        /** WatchlistBrief */
        WatchlistBrief: {
            /** Change Pct 24H */
            change_pct_24h: string;
            /** Inst Id */
            inst_id: string;
            /** Last Price */
            last_price: string;
            /** Product Key */
            product_key: string;
        };
        /**
         * WatchlistItem
         * @description 自选列表一行：行情快照 + 关联运行态。
         * @example {
         *       "change_pct_24h": "1.86",
         *       "group": "美股",
         *       "instrument": {
         *         "asset_type": "tokenized_equity",
         *         "base_currency": "XAAPL",
         *         "inst_id": "XAAPL-USDT",
         *         "inst_type": "SPOT",
         *         "listing_time": "2026-07-01T00:00:00Z",
         *         "lot_size": "0.001",
         *         "min_order_size": "0.001",
         *         "product_key": "AAPL",
         *         "quote_currency": "USDT",
         *         "tick_size": "0.01",
         *         "trading_status": "live"
         *       },
         *       "last_price": "231.42",
         *       "latest_signal": {
         *         "action": "BUY",
         *         "bar": "1h",
         *         "generated_at": "2026-11-10T07:00:00Z",
         *         "inst_id": "XAAPL-USDT",
         *         "inst_type": "SPOT",
         *         "price": "231.42",
         *         "reason": "MA20 上穿 MA60",
         *         "signal_id": "sig_0001",
         *         "strategy_instance_id": "si_0001",
         *         "target_weight": "0.25"
         *       },
         *       "linked_strategy_instance_ids": [
         *         "si_0001"
         *       ],
         *       "volume_24h_quote": "4821334.55"
         *     }
         */
        WatchlistItem: {
            alert?: components["schemas"]["PriceAlert"] | null;
            /** Change Pct 24H */
            change_pct_24h: string;
            /** Group */
            group: string;
            instrument: components["schemas"]["InstrumentInfo"];
            /** Last Price */
            last_price: string;
            latest_signal?: components["schemas"]["Signal"] | null;
            /** Linked Strategy Instance Ids */
            linked_strategy_instance_ids?: string[];
            /** Volume 24H Quote */
            volume_24h_quote: string;
        };
        /**
         * WatchlistResponse
         * @example {
         *       "groups": [
         *         "美股",
         *         "加密"
         *       ],
         *       "items": [
         *         {
         *           "change_pct_24h": "1.86",
         *           "group": "美股",
         *           "instrument": {
         *             "asset_type": "tokenized_equity",
         *             "base_currency": "XAAPL",
         *             "inst_id": "XAAPL-USDT",
         *             "inst_type": "SPOT",
         *             "listing_time": "2026-07-01T00:00:00Z",
         *             "lot_size": "0.001",
         *             "min_order_size": "0.001",
         *             "product_key": "AAPL",
         *             "quote_currency": "USDT",
         *             "tick_size": "0.01",
         *             "trading_status": "live"
         *           },
         *           "last_price": "231.42",
         *           "latest_signal": {
         *             "action": "BUY",
         *             "bar": "1h",
         *             "generated_at": "2026-11-10T07:00:00Z",
         *             "inst_id": "XAAPL-USDT",
         *             "inst_type": "SPOT",
         *             "price": "231.42",
         *             "reason": "MA20 上穿 MA60",
         *             "signal_id": "sig_0001",
         *             "strategy_instance_id": "si_0001",
         *             "target_weight": "0.25"
         *           },
         *           "linked_strategy_instance_ids": [
         *             "si_0001"
         *           ],
         *           "volume_24h_quote": "4821334.55"
         *         }
         *       ]
         *     }
         */
        WatchlistResponse: {
            /** Groups */
            groups: string[];
            /** Items */
            items: components["schemas"]["WatchlistItem"][];
        };
        /** WatchlistUpdateRequest */
        WatchlistUpdateRequest: {
            /** Group */
            group: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    create_backtest_sweep_api_backtest_sweeps_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BacktestSweepRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BacktestSweepResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_backtests_api_backtests_get: {
        parameters: {
            query: {
                data_source: "okx" | "us_equity_proxy";
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BacktestRunListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_backtest_api_backtests_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BacktestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BacktestRunSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backtest_ranking_api_backtests_ranking_get: {
        parameters: {
            query: {
                data_source: "okx" | "us_equity_proxy";
                metric?: "total_return_pct" | "max_drawdown_pct" | "sharpe" | "profit_factor";
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BacktestRankingResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backtest_api_backtests__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BacktestDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_backtest_api_backtests__run_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_execution_state_api_execution_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionStateResponse"];
                };
            };
        };
    };
    set_execution_mode_api_execution_mode_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExecutionModeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionStateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    list_indicators_api_indicators_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IndicatorCatalogResponse"];
                };
            };
        };
    };
    get_indicator_series_api_indicators_series_get: {
        parameters: {
            query: {
                inst_id: string;
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                /** @description 逗号分隔的指标名 (如 rsi,sma) */
                names: string;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IndicatorSeriesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    search_instruments_api_instruments_search_get: {
        parameters: {
            query: {
                q: string;
                inst_type?: ("SPOT" | "SWAP") | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstrumentSearchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_instrument_api_instruments__inst_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstrumentDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_instrument_candles_api_instruments__inst_id__candles_get: {
        parameters: {
            query: {
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                limit?: number;
            };
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CandleSeriesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_journal_api_journal_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JournalListResponse"];
                };
            };
        };
    };
    get_overview_api_overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverviewResponse"];
                };
            };
        };
    };
    get_settings_document_api_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsResponse"];
                };
            };
        };
    };
    update_settings_document_api_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SettingsUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_signals_api_signals_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SignalListResponse"];
                };
            };
        };
    };
    list_strategies_api_strategies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyCatalogResponse"];
                };
            };
        };
    };
    list_strategy_instances_api_strategy_instances_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyInstanceListResponse"];
                };
            };
        };
    };
    create_strategy_instance_api_strategy_instances_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyInstanceCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyInstance"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_strategy_instance_api_strategy_instances__instance_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyInstance"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_strategy_instance_api_strategy_instances__instance_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_strategy_instance_api_strategy_instances__instance_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                instance_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyInstanceUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyInstance"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_fills_api_trades_fills_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FillListResponse"];
                };
            };
        };
    };
    list_orders_api_trades_orders_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderListResponse"];
                };
            };
        };
    };
    create_order_api_trades_orders_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OrderCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Order"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_order_api_trades_orders__order_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                order_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_positions_api_trades_positions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PositionListResponse"];
                };
            };
        };
    };
    list_watchlist_api_watchlist_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchlistResponse"];
                };
            };
        };
    };
    add_watchlist_item_api_watchlist_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WatchlistAddRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchlistItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_watchlist_item_api_watchlist__inst_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_watchlist_item_api_watchlist__inst_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WatchlistUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WatchlistItem"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_price_alert_api_watchlist__inst_id__alert_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PriceAlertRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PriceAlert"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_price_alert_api_watchlist__inst_id__alert_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_related_instruments_api_watchlist__inst_id__related_get: {
        parameters: {
            query?: {
                window_days?: number;
            };
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RelatedInstrumentsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
