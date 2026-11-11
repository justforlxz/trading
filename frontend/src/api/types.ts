// 由 `pnpm --dir frontend api:sync` 生成，勿手改。契约源：backend/contracts/openapi.json
export interface paths {
    "/api/approvals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Approvals */
        get: operations["list_approvals_api_approvals_get"];
        put?: never;
        /** Submit For Review */
        post: operations["submit_for_review_api_approvals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/approvals/{instance_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Strategy */
        post: operations["approve_strategy_api_approvals__instance_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/approvals/{instance_id}/live-authorization": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Authorize Live Trading */
        post: operations["authorize_live_trading_api_approvals__instance_id__live_authorization_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/approvals/{instance_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Strategy */
        post: operations["reject_strategy_api_approvals__instance_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
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
    "/api/correlation/matrix": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Correlation Matrix */
        get: operations["get_correlation_matrix_api_correlation_matrix_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/correlation/series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Correlation Series */
        get: operations["get_correlation_series_api_correlation_series_get"];
        put?: never;
        post?: never;
        delete?: never;
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
        /**
         * List Indicators
         * @description 指标目录：每条声明都来自注册表，形状与 `schemas/indicators.py` 一一对应。
         */
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
        /**
         * Get Indicator Series
         * @description 按标的与周期算一组指标；参数缺省用注册表默认值，缺数据时序列为空。
         */
        get: operations["get_indicator_series_api_indicators_series_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Tradable Instruments
         * @description 某一类别的可交易标的（`state == live`），不按资产类别过滤。
         */
        get: operations["list_tradable_instruments_api_instruments_get"];
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
    "/api/market/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Market Overview */
        get: operations["get_market_overview_api_market_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/opportunities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Opportunities */
        get: operations["list_opportunities_api_opportunities_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/opportunities/{opportunity_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Opportunity */
        get: operations["get_opportunity_api_opportunities__opportunity_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Opportunity Status */
        patch: operations["update_opportunity_status_api_opportunities__opportunity_id__patch"];
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
    "/api/portfolio/adjustments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Portfolio Adjustments */
        get: operations["list_portfolio_adjustments_api_portfolio_adjustments_get"];
        put?: never;
        /** Create Portfolio Adjustment */
        post: operations["create_portfolio_adjustment_api_portfolio_adjustments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/portfolio/adjustments/{adjustment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Decide Portfolio Adjustment */
        patch: operations["decide_portfolio_adjustment_api_portfolio_adjustments__adjustment_id__patch"];
        trace?: never;
    };
    "/api/portfolio/exposure": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Portfolio Exposure */
        get: operations["get_portfolio_exposure_api_portfolio_exposure_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/portfolio/strategies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Strategy Portfolios */
        get: operations["list_strategy_portfolios_api_portfolio_strategies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/portfolio/strategies/{instance_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Strategy Portfolio */
        get: operations["get_strategy_portfolio_api_portfolio_strategies__instance_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/relations/graph": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Relation Graph */
        get: operations["get_relation_graph_api_relations_graph_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/relations/neighbors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Relation Neighbors */
        get: operations["get_relation_neighbors_api_relations_neighbors_get"];
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
            data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
            /**
             * Has Gap
             * @default false
             */
            has_gap: boolean;
            /** Inst Id */
            inst_id: string;
        };
        /**
         * CorrelationCell
         * @description 矩阵的一格；`coefficient` 为 `null` 表示该格样本不足。
         */
        CorrelationCell: {
            /** Coefficient */
            coefficient: string | null;
            /** Product Key A */
            product_key_a: string;
            /** Product Key B */
            product_key_b: string;
            /** Samples */
            samples: number;
        };
        /**
         * CorrelationMatrixResponse
         * @description 某一时点、某一周期、某一窗口的整张相关矩阵（格子全量给出，含对角线）。
         * @example {
         *       "as_of": "2026-11-10T00:00:00Z",
         *       "bar": "1d",
         *       "cells": [
         *         {
         *           "coefficient": "1",
         *           "product_key_a": "AAPL",
         *           "product_key_b": "AAPL",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "0.87",
         *           "product_key_a": "AAPL",
         *           "product_key_b": "MSFT",
         *           "samples": 60
         *         },
         *         {
         *           "product_key_a": "AAPL",
         *           "product_key_b": "NVDA",
         *           "samples": 2
         *         },
         *         {
         *           "coefficient": "0.87",
         *           "product_key_a": "MSFT",
         *           "product_key_b": "AAPL",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "1",
         *           "product_key_a": "MSFT",
         *           "product_key_b": "MSFT",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "0.64",
         *           "product_key_a": "MSFT",
         *           "product_key_b": "NVDA",
         *           "samples": 60
         *         },
         *         {
         *           "product_key_a": "NVDA",
         *           "product_key_b": "AAPL",
         *           "samples": 2
         *         },
         *         {
         *           "coefficient": "0.64",
         *           "product_key_a": "NVDA",
         *           "product_key_b": "MSFT",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "1",
         *           "product_key_a": "NVDA",
         *           "product_key_b": "NVDA",
         *           "samples": 60
         *         }
         *       ],
         *       "product_keys": [
         *         "AAPL",
         *         "MSFT",
         *         "NVDA"
         *       ],
         *       "window": 60
         *     }
         */
        CorrelationMatrixResponse: {
            /** As Of */
            as_of: string;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Cells */
            cells: components["schemas"]["CorrelationCell"][];
            /** Product Keys */
            product_keys: string[];
            /** Window */
            window: number;
        };
        /**
         * CorrelationPoint
         * @description 滚动相关序列上的一个点；样本不足时 `coefficient` 为 `null`。
         */
        CorrelationPoint: {
            /** As Of */
            as_of: string;
            /** Coefficient */
            coefficient: string | null;
            /** Samples */
            samples: number;
        };
        /**
         * CorrelationSeriesResponse
         * @description 两个标的在滚动窗口上的相关性随时间的变化。
         * @example {
         *       "available_from": "2026-10-01T00:00:00Z",
         *       "available_to": "2026-11-10T00:00:00Z",
         *       "bar": "1d",
         *       "points": [
         *         {
         *           "as_of": "2026-11-08T00:00:00Z",
         *           "coefficient": "0.83",
         *           "samples": 30
         *         },
         *         {
         *           "as_of": "2026-11-09T00:00:00Z",
         *           "coefficient": "0.85",
         *           "samples": 30
         *         },
         *         {
         *           "as_of": "2026-11-10T00:00:00Z",
         *           "coefficient": "0.87",
         *           "samples": 30
         *         }
         *       ],
         *       "product_key_a": "AAPL",
         *       "product_key_b": "MSFT",
         *       "window": 30
         *     }
         */
        CorrelationSeriesResponse: {
            /** Available From */
            available_from?: string | null;
            /** Available To */
            available_to?: string | null;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Points */
            points: components["schemas"]["CorrelationPoint"][];
            /** Product Key A */
            product_key_a: string;
            /** Product Key B */
            product_key_b: string;
            /** Window */
            window: number;
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
        /**
         * ExposureOverviewResponse
         * @description 全局敞口总览。`largest_position_share` 是单一标的最大权重占组合权益的比例。
         * @example {
         *       "conflicts": [
         *         {
         *           "long_instance_ids": [
         *             "si_0001"
         *           ],
         *           "product_key": "AAPL",
         *           "short_instance_ids": [
         *             "si_0002"
         *           ]
         *         }
         *       ],
         *       "generated_at": "2026-11-10T08:00:00Z",
         *       "gross_exposure": "3510.40",
         *       "largest_position_share": "0.24",
         *       "long_exposure": "2753.78",
         *       "net_exposure": "1997.15",
         *       "open_positions": 3,
         *       "product_count": 2,
         *       "short_exposure": "756.62"
         *     }
         */
        ExposureOverviewResponse: {
            /** Conflicts */
            conflicts: components["schemas"]["PortfolioConflict"][];
            /** Generated At */
            generated_at: string;
            /** Gross Exposure */
            gross_exposure: string;
            /** Largest Position Share */
            largest_position_share: string;
            /** Long Exposure */
            long_exposure: string;
            /** Net Exposure */
            net_exposure: string;
            /** Open Positions */
            open_positions: number;
            /** Product Count */
            product_count: number;
            /** Short Exposure */
            short_exposure: string;
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
         * InstrumentListResponse
         * @description 某一类别的可交易标的（`state == live`）；交易参数走详情端点。
         * @example {
         *       "items": [
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
        InstrumentListResponse: {
            /** Items */
            items: components["schemas"]["InstrumentRef"][];
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
         * LiveAuthorizationRequest
         * @description 申请实盘授权：记录授权人与已批准的资金预算，不打开实盘开关。
         */
        LiveAuthorizationRequest: {
            /** Actor */
            actor: string;
            /** Capital Budget */
            capital_budget: string;
            /** Evidence */
            evidence?: string | null;
            /** Note */
            note?: string | null;
        };
        /**
         * MarketBreadth
         * @description 某一类别在某一时点上的涨跌家数。
         *
         *     `ratio` 是上涨家数除以下跌家数；没有下跌标的时除以零不成立，如实给 `null`，
         *     不写成无穷大或一个很大的数。`unchanged` 是涨跌幅恰好为零的标的数。
         */
        MarketBreadth: {
            /** Advancers */
            advancers: number;
            /** Decliners */
            decliners: number;
            /** Participants */
            participants: number;
            /** Ratio */
            ratio: string | null;
            /** Unchanged */
            unchanged: number;
        };
        /**
         * MarketOverviewResponse
         * @description 某一类别（`inst_type`）的横截面总览；两类标的各自统计，互不混入。
         * @example {
         *       "as_of": "2026-11-10T00:00:00Z",
         *       "bar": "1d",
         *       "breadth": {
         *         "advancers": 8,
         *         "decliners": 2,
         *         "participants": 11,
         *         "ratio": "4",
         *         "unchanged": 1
         *       },
         *       "inst_type": "SPOT",
         *       "resonance": {
         *         "participants": 11,
         *         "strength": "0.62",
         *         "window": 20
         *       }
         *     }
         */
        MarketOverviewResponse: {
            /** As Of */
            as_of: string;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            breadth: components["schemas"]["MarketBreadth"];
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            resonance: components["schemas"]["MarketResonance"];
        };
        /**
         * MarketResonance
         * @description 同一类别内部的同向程度：全部同向上涨为 1，涨跌各半为 0，恒在 [0, 1]。
         *
         *     参与标的少于 5 个时不给数（`strength` 为 `null`）：样本不足时的「共振强度」
         *     没有意义，编一个数字比留空更糟。
         */
        MarketResonance: {
            /** Participants */
            participants: number;
            /** Strength */
            strength: string | null;
            /** Window */
            window: number;
        };
        /**
         * Opportunity
         * @description 一条机会记录。
         *
         *     `evidence` 是判定依据的 JSON 文本（相关系数、广度、共振强度等），原样透传，
         *     不在契约层二次解释；`score` 是筛选用的综合分数。
         * @example {
         *       "anchor_product_key": "AAPL",
         *       "as_of": "2026-11-10T00:00:00Z",
         *       "evidence": "{\"correlation\":0.87,\"breadth\":0.8,\"resonance\":0.62}",
         *       "legs": [
         *         {
         *           "direction": "long",
         *           "inst_id": "MSFT-USDT-SWAP",
         *           "inst_type": "SWAP",
         *           "product_key": "MSFT",
         *           "score": "0.82"
         *         },
         *         {
         *           "direction": "short",
         *           "inst_id": "NVDA-USDT-SWAP",
         *           "inst_type": "SWAP",
         *           "product_key": "NVDA",
         *           "score": "0.71"
         *         }
         *       ],
         *       "mode": "target",
         *       "opportunity_id": "opp_0001",
         *       "score": "0.78",
         *       "status": "new"
         *     }
         */
        Opportunity: {
            /** Anchor Product Key */
            anchor_product_key?: string | null;
            /** As Of */
            as_of: string;
            /** Evidence */
            evidence: string;
            /** Legs */
            legs: components["schemas"]["OpportunityLeg"][];
            /**
             * Mode
             * @enum {string}
             */
            mode: "target" | "market";
            /** Opportunity Id */
            opportunity_id: string;
            /** Score */
            score: string;
            /**
             * Status
             * @enum {string}
             */
            status: "new" | "reviewed" | "adopted" | "rejected" | "expired";
        };
        /**
         * OpportunityLeg
         * @description 候选腿：某个标的方向与得分。目标权重由 T3.5 的组合生成阶段给出。
         */
        OpportunityLeg: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "long" | "short";
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Product Key */
            product_key: string;
            /** Score */
            score: string;
        };
        /**
         * OpportunityListResponse
         * @example {
         *       "items": [
         *         {
         *           "anchor_product_key": "AAPL",
         *           "as_of": "2026-11-10T00:00:00Z",
         *           "evidence": "{\"correlation\":0.87,\"breadth\":0.8,\"resonance\":0.62}",
         *           "legs": [
         *             {
         *               "direction": "long",
         *               "inst_id": "MSFT-USDT-SWAP",
         *               "inst_type": "SWAP",
         *               "product_key": "MSFT",
         *               "score": "0.82"
         *             },
         *             {
         *               "direction": "short",
         *               "inst_id": "NVDA-USDT-SWAP",
         *               "inst_type": "SWAP",
         *               "product_key": "NVDA",
         *               "score": "0.71"
         *             }
         *           ],
         *           "mode": "target",
         *           "opportunity_id": "opp_0001",
         *           "score": "0.78",
         *           "status": "new"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        OpportunityListResponse: {
            /** Items */
            items: components["schemas"]["Opportunity"][];
            /** Total */
            total: number;
        };
        /**
         * OpportunityStatusUpdateRequest
         * @description 状态变更请求：目标状态必须是取值集合内、且是 `status` 允许的下一步。
         */
        OpportunityStatusUpdateRequest: {
            /**
             * Status
             * @enum {string}
             */
            status: "new" | "reviewed" | "adopted" | "rejected" | "expired";
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
         *           "status": "paper_trading",
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
        /**
         * PortfolioAdjustment
         * @description 一条组合调整申请；批准之前 `target` 不生效。
         * @example {
         *       "adjustment_id": "adj_0001",
         *       "instance_id": "si_0001",
         *       "note": "把 AAPL 目标权重从 0.25 提到 0.30",
         *       "requested_at": "2026-11-10T07:30:00Z",
         *       "requested_by": "lxz",
         *       "status": "pending",
         *       "target": {
         *         "legs": [
         *           {
         *             "direction": "long",
         *             "inst_id": "XAAPL-USDT",
         *             "inst_type": "SPOT",
         *             "qty": "8.63",
         *             "target_weight": "0.25",
         *             "unit": "base"
         *           }
         *         ],
         *         "net_exposure": "0.25"
         *       }
         *     }
         */
        PortfolioAdjustment: {
            /** Adjustment Id */
            adjustment_id: string;
            /** Decided At */
            decided_at?: string | null;
            /** Decided By */
            decided_by?: string | null;
            /** Instance Id */
            instance_id: string;
            /** Note */
            note?: string | null;
            /** Requested At */
            requested_at: string;
            /** Requested By */
            requested_by: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "approved" | "rejected";
            target: components["schemas"]["TargetPortfolio"];
        };
        /**
         * PortfolioAdjustmentCreateRequest
         * @description 提交调整申请：只写申请，不改生效状态。
         */
        PortfolioAdjustmentCreateRequest: {
            /** Instance Id */
            instance_id: string;
            /** Note */
            note?: string | null;
            /** Requested By */
            requested_by: string;
            target: components["schemas"]["TargetPortfolio"];
        };
        /**
         * PortfolioAdjustmentDecisionRequest
         * @description 批准或驳回一条申请；决定必须由人工作出。
         */
        PortfolioAdjustmentDecisionRequest: {
            /** Decided By */
            decided_by: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "approved" | "rejected";
            /** Note */
            note?: string | null;
        };
        /**
         * PortfolioAdjustmentListResponse
         * @example {
         *       "items": [
         *         {
         *           "adjustment_id": "adj_0001",
         *           "instance_id": "si_0001",
         *           "note": "把 AAPL 目标权重从 0.25 提到 0.30",
         *           "requested_at": "2026-11-10T07:30:00Z",
         *           "requested_by": "lxz",
         *           "status": "pending",
         *           "target": {
         *             "legs": [
         *               {
         *                 "direction": "long",
         *                 "inst_id": "XAAPL-USDT",
         *                 "inst_type": "SPOT",
         *                 "qty": "8.63",
         *                 "target_weight": "0.25",
         *                 "unit": "base"
         *               }
         *             ],
         *             "net_exposure": "0.25"
         *           }
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        PortfolioAdjustmentListResponse: {
            /** Items */
            items: components["schemas"]["PortfolioAdjustment"][];
            /** Total */
            total: number;
        };
        /**
         * PortfolioConflict
         * @description 同一 `product_key` 在多个策略上方向相反；两侧策略都要列出，不合并成一条。
         */
        PortfolioConflict: {
            /** Long Instance Ids */
            long_instance_ids: string[];
            /** Product Key */
            product_key: string;
            /** Short Instance Ids */
            short_instance_ids: string[];
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
         * RelationCommunity
         * @description 一个社区：编号由社区划分算法给出，成员是标的的 `product_key`。
         */
        RelationCommunity: {
            /** Community Id */
            community_id: number;
            /** Product Keys */
            product_keys: string[];
        };
        /**
         * RelationEdge
         * @description 一条相关边；`samples` 是算这个系数时实际用到的样本条数。
         */
        RelationEdge: {
            /** Coefficient */
            coefficient: string;
            /** Product Key A */
            product_key_a: string;
            /** Product Key B */
            product_key_b: string;
            /** Samples */
            samples: number;
        };
        /**
         * RelationGraphResponse
         * @description 一次请求返回一张完整的小图：节点、边、社区与图级平均连通度。
         * @example {
         *       "as_of": "2026-11-10T00:00:00Z",
         *       "average_degree": "1.75",
         *       "bar": "1d",
         *       "communities": [
         *         {
         *           "community_id": 0,
         *           "product_keys": [
         *             "AAPL",
         *             "MSFT"
         *           ]
         *         },
         *         {
         *           "community_id": 1,
         *           "product_keys": [
         *             "NVDA",
         *             "TSLA"
         *           ]
         *         }
         *       ],
         *       "edges": [
         *         {
         *           "coefficient": "0.87",
         *           "product_key_a": "AAPL",
         *           "product_key_b": "MSFT",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "-0.64",
         *           "product_key_a": "AAPL",
         *           "product_key_b": "NVDA",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "-0.64",
         *           "product_key_a": "MSFT",
         *           "product_key_b": "NVDA",
         *           "samples": 60
         *         },
         *         {
         *           "coefficient": "0.58",
         *           "product_key_a": "NVDA",
         *           "product_key_b": "TSLA",
         *           "samples": 60
         *         }
         *       ],
         *       "min_abs_corr": "0.5",
         *       "nodes": [
         *         {
         *           "asset_type": "tokenized_equity",
         *           "centrality": "0.67",
         *           "community_id": 0,
         *           "degree": 2,
         *           "product_key": "AAPL"
         *         },
         *         {
         *           "asset_type": "tokenized_equity",
         *           "centrality": "0.67",
         *           "community_id": 0,
         *           "degree": 2,
         *           "product_key": "MSFT"
         *         },
         *         {
         *           "asset_type": "tokenized_equity",
         *           "centrality": "0.67",
         *           "community_id": 1,
         *           "degree": 2,
         *           "product_key": "NVDA"
         *         },
         *         {
         *           "asset_type": "tokenized_equity",
         *           "centrality": "0.33",
         *           "community_id": 1,
         *           "degree": 1,
         *           "product_key": "TSLA"
         *         }
         *       ],
         *       "window": 60
         *     }
         */
        RelationGraphResponse: {
            /** As Of */
            as_of: string;
            /** Average Degree */
            average_degree: string;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Communities */
            communities: components["schemas"]["RelationCommunity"][];
            /** Edges */
            edges: components["schemas"]["RelationEdge"][];
            /** Min Abs Corr */
            min_abs_corr: string;
            /** Nodes */
            nodes: components["schemas"]["RelationNode"][];
            /** Window */
            window: number;
        };
        /**
         * RelationNeighbor
         * @description 某个标的的邻居及其系数；按系数绝对值从大到小排列。
         */
        RelationNeighbor: {
            /**
             * Asset Type
             * @enum {string}
             */
            asset_type: "tokenized_equity" | "crypto" | "commodity_token" | "unknown";
            /** Coefficient */
            coefficient: string;
            /** Product Key */
            product_key: string;
            /** Samples */
            samples: number;
        };
        /**
         * RelationNeighborsResponse
         * @example {
         *       "bar": "1d",
         *       "items": [
         *         {
         *           "asset_type": "tokenized_equity",
         *           "coefficient": "0.87",
         *           "product_key": "MSFT",
         *           "samples": 60
         *         },
         *         {
         *           "asset_type": "tokenized_equity",
         *           "coefficient": "-0.64",
         *           "product_key": "NVDA",
         *           "samples": 60
         *         }
         *       ],
         *       "product_key": "AAPL",
         *       "window": 60
         *     }
         */
        RelationNeighborsResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Items */
            items: components["schemas"]["RelationNeighbor"][];
            /** Product Key */
            product_key: string;
            /** Window */
            window: number;
        };
        /**
         * RelationNode
         * @description 网络里的一个标的及其网络指标（度数、中心性、所属社区）。
         */
        RelationNode: {
            /**
             * Asset Type
             * @enum {string}
             */
            asset_type: "tokenized_equity" | "crypto" | "commodity_token" | "unknown";
            /** Centrality */
            centrality: string;
            /** Community Id */
            community_id: number;
            /** Degree */
            degree: number;
            /** Product Key */
            product_key: string;
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
        /**
         * StrategyApprovalDecisionRequest
         * @description 审核决定：通过或驳回。驳回只能回到 `strategy_generation`。
         */
        StrategyApprovalDecisionRequest: {
            /** Actor */
            actor: string;
            /** Evidence */
            evidence?: string | null;
            /** Note */
            note?: string | null;
        };
        /**
         * StrategyApprovalListResponse
         * @example {
         *       "items": [
         *         {
         *           "actor": "lxz",
         *           "approval_id": "apr_0001",
         *           "at": "2026-11-10T07:10:00Z",
         *           "from_status": "strategy_generation",
         *           "instance_id": "si_0001",
         *           "note": "提交人工审核",
         *           "to_status": "pending_review"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        StrategyApprovalListResponse: {
            /** Items */
            items: components["schemas"]["StrategyApprovalTransition"][];
            /** Total */
            total: number;
        };
        /**
         * StrategyApprovalRequest
         * @description 提交人工审核：策略实例从「已生成」进入待审核，不改策略配置。
         */
        StrategyApprovalRequest: {
            /** Actor */
            actor: string;
            /** Instance Id */
            instance_id: string;
            /** Note */
            note?: string | null;
        };
        /**
         * StrategyApprovalTransition
         * @description 一次状态推进记录。
         *
         *     `from_status` 为 `null` 表示该实例的第一条记录（从「已生成」进入审核）。
         *     `evidence` 是推进依据的引用，例如量化验证的达标报告编号；没有依据的推进留空。
         * @example {
         *       "actor": "lxz",
         *       "approval_id": "apr_0001",
         *       "at": "2026-11-10T07:10:00Z",
         *       "from_status": "strategy_generation",
         *       "instance_id": "si_0001",
         *       "note": "提交人工审核",
         *       "to_status": "pending_review"
         *     }
         */
        StrategyApprovalTransition: {
            /** Actor */
            actor: string;
            /** Approval Id */
            approval_id: string;
            /** At */
            at: string;
            /** Evidence */
            evidence?: string | null;
            /** From Status */
            from_status?: ("opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected") | null;
            /** Instance Id */
            instance_id: string;
            /** Note */
            note?: string | null;
            /**
             * To Status
             * @enum {string}
             */
            to_status: "opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected";
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
            status: "opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected";
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
         *       "enabled": true,
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
         *       "status": "paper_trading",
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
             * Enabled
             * @default true
             */
            enabled: boolean;
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
            status: "opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected";
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
         *           "enabled": true,
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
         *           "status": "paper_trading",
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
         *
         *     生命周期阶段**不在这条端点上改**：阶段推进只经 `/api/approvals` 的状态机，
         *     否则一次 PATCH 就能从草稿跳到实盘运行，绕过人工审核、历史回测与量化验证
         *     （`docs/prd/v2.md` §三.5「任何阶段都不能被跳过」）。提交 `status` 会因
         *     `extra="forbid"` 直接 422，不会静默忽略。
         *
         *     `enabled` 是实例的启停开关，只决定它是否产出信号，不改变生命周期阶段。
         */
        StrategyInstanceUpdateRequest: {
            /** Enabled */
            enabled?: boolean | null;
            /** Inst Ids */
            inst_ids?: string[] | null;
            /** Name */
            name?: string | null;
            /** Params */
            params?: {
                [key: string]: number | string | boolean;
            } | null;
        };
        /**
         * StrategyPortfolio
         * @description 一个策略实例的资金与敞口概览（组合列表的一行）。
         *
         *     `priority` 越大越优先；`capital_budget` 是已批准给该策略的资金预算。
         */
        StrategyPortfolio: {
            /** Capital Budget */
            capital_budget: string;
            /** Gross Exposure */
            gross_exposure: string;
            /** Instance Id */
            instance_id: string;
            /**
             * Lifecycle Status
             * @enum {string}
             */
            lifecycle_status: "opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected";
            /** Name */
            name: string;
            /** Net Exposure */
            net_exposure: string;
            /** Open Positions */
            open_positions: number;
            /** Priority */
            priority: number;
            /** Realized Pnl */
            realized_pnl: string;
            /** Strategy Id */
            strategy_id: string;
            /** Unrealized Pnl */
            unrealized_pnl: string;
        };
        /**
         * StrategyPortfolioDetailResponse
         * @description 单个策略的明细：资金与敞口、虚拟持仓、当前生效的目标组合（尚未生成时为 `null`）。
         * @example {
         *       "portfolio": {
         *         "capital_budget": "2000.00",
         *         "gross_exposure": "1997.15",
         *         "instance_id": "si_0001",
         *         "lifecycle_status": "live_running",
         *         "name": "AAPL 均线趋势",
         *         "net_exposure": "1997.15",
         *         "open_positions": 1,
         *         "priority": 10,
         *         "realized_pnl": "12.05",
         *         "strategy_id": "ma_cross",
         *         "unrealized_pnl": "28.64"
         *       },
         *       "positions": [
         *         {
         *           "avg_cost": "228.10",
         *           "direction": "long",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "mark_price": "231.42",
         *           "notional": "1997.15",
         *           "opened_at": "2026-11-09T14:00:00Z",
         *           "product_key": "AAPL",
         *           "qty": "8.63",
         *           "unit": "base",
         *           "unrealized_pnl": "28.64"
         *         }
         *       ],
         *       "target": {
         *         "legs": [
         *           {
         *             "direction": "long",
         *             "inst_id": "XAAPL-USDT",
         *             "inst_type": "SPOT",
         *             "qty": "8.63",
         *             "target_weight": "0.25",
         *             "unit": "base"
         *           }
         *         ],
         *         "net_exposure": "0.25"
         *       }
         *     }
         */
        StrategyPortfolioDetailResponse: {
            portfolio: components["schemas"]["StrategyPortfolio"];
            /** Positions */
            positions: components["schemas"]["VirtualPosition"][];
            target?: components["schemas"]["TargetPortfolio"] | null;
        };
        /**
         * StrategyPortfolioListResponse
         * @example {
         *       "items": [
         *         {
         *           "capital_budget": "2000.00",
         *           "gross_exposure": "1997.15",
         *           "instance_id": "si_0001",
         *           "lifecycle_status": "live_running",
         *           "name": "AAPL 均线趋势",
         *           "net_exposure": "1997.15",
         *           "open_positions": 1,
         *           "priority": 10,
         *           "realized_pnl": "12.05",
         *           "strategy_id": "ma_cross",
         *           "unrealized_pnl": "28.64"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        StrategyPortfolioListResponse: {
            /** Items */
            items: components["schemas"]["StrategyPortfolio"][];
            /** Total */
            total: number;
        };
        /**
         * TargetLeg
         * @description 目标组合的一条腿：某个标的、某个方向、某个目标权重。
         *
         *     `target_weight` 是权重（占组合资金的比例，正数表示该腿的大小），方向单独由
         *     `direction` 表达——不用权重符号再编码一次方向。
         *
         *     `qty` 与 `unit` 是**服务端换算出的**下单数量：`SPOT` 按标的币数量（`base`），
         *     `SWAP` 按合约张数（`contract`），换算依赖价格、合约面值与精度，前端不做这类
         *     派生计算（`AGENTS.md` §6）。因此请求里可以不带这两个字段，由服务端在生成目标
         *     组合时填入；读到 `null` 表示这一步尚未换算。
         */
        TargetLeg: {
            /**
             * Direction
             * @enum {string}
             */
            direction: "long" | "short";
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Qty */
            qty?: string | null;
            /** Target Weight */
            target_weight: string;
            /** Unit */
            unit?: ("base" | "contract") | null;
        };
        /**
         * TargetPortfolio
         * @description 目标组合：多腿、多空并存，`net_exposure` 是多头权重之和减空头权重之和。
         */
        TargetPortfolio: {
            /** Legs */
            legs: components["schemas"]["TargetLeg"][];
            /** Net Exposure */
            net_exposure: string;
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
        /**
         * VirtualPosition
         * @description 策略账本里的一条持仓；`avg_cost` 是当前剩余持仓的成本价（FIFO 核算后）。
         */
        VirtualPosition: {
            /** Avg Cost */
            avg_cost: string;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long" | "short";
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Mark Price */
            mark_price: string;
            /** Notional */
            notional: string;
            /** Opened At */
            opened_at: string;
            /** Product Key */
            product_key: string;
            /** Qty */
            qty: string;
            /**
             * Unit
             * @enum {string}
             */
            unit: "base" | "contract";
            /** Unrealized Pnl */
            unrealized_pnl: string;
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
    list_approvals_api_approvals_get: {
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
                    "application/json": components["schemas"]["StrategyApprovalListResponse"];
                };
            };
        };
    };
    submit_for_review_api_approvals_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyApprovalRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyApprovalTransition"];
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
    approve_strategy_api_approvals__instance_id__approve_post: {
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
                "application/json": components["schemas"]["StrategyApprovalDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyApprovalTransition"];
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
    authorize_live_trading_api_approvals__instance_id__live_authorization_post: {
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
                "application/json": components["schemas"]["LiveAuthorizationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyApprovalTransition"];
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
    reject_strategy_api_approvals__instance_id__reject_post: {
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
                "application/json": components["schemas"]["StrategyApprovalDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyApprovalTransition"];
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
                data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
                data_source: "okx" | "okx_spot" | "okx_swap" | "us_equity_proxy";
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
    get_correlation_matrix_api_correlation_matrix_get: {
        parameters: {
            query: {
                product_keys: string[];
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                window: number;
                as_of?: string | null;
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
                    "application/json": components["schemas"]["CorrelationMatrixResponse"];
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
    get_correlation_series_api_correlation_series_get: {
        parameters: {
            query: {
                product_key_a: string;
                product_key_b: string;
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                window: number;
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
                    "application/json": components["schemas"]["CorrelationSeriesResponse"];
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
                /** @description 可选参数通道, JSON 对象形如 {"rsi":{"period":14},"sma":{"period":20}} */
                params?: string | null;
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
    list_tradable_instruments_api_instruments_get: {
        parameters: {
            query: {
                inst_type: "SPOT" | "SWAP";
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
                    "application/json": components["schemas"]["InstrumentListResponse"];
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
    get_market_overview_api_market_overview_get: {
        parameters: {
            query: {
                inst_type: "SPOT" | "SWAP";
                bar?: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                as_of?: string | null;
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
                    "application/json": components["schemas"]["MarketOverviewResponse"];
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
    list_opportunities_api_opportunities_get: {
        parameters: {
            query?: {
                mode?: ("target" | "market") | null;
                anchor_product_key?: string | null;
                status?: ("new" | "reviewed" | "adopted" | "rejected" | "expired") | null;
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
                    "application/json": components["schemas"]["OpportunityListResponse"];
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
    get_opportunity_api_opportunities__opportunity_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                opportunity_id: string;
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
                    "application/json": components["schemas"]["Opportunity"];
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
    update_opportunity_status_api_opportunities__opportunity_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                opportunity_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OpportunityStatusUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Opportunity"];
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
    list_portfolio_adjustments_api_portfolio_adjustments_get: {
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
                    "application/json": components["schemas"]["PortfolioAdjustmentListResponse"];
                };
            };
        };
    };
    create_portfolio_adjustment_api_portfolio_adjustments_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioAdjustmentCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioAdjustment"];
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
    decide_portfolio_adjustment_api_portfolio_adjustments__adjustment_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                adjustment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioAdjustmentDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioAdjustment"];
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
    get_portfolio_exposure_api_portfolio_exposure_get: {
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
                    "application/json": components["schemas"]["ExposureOverviewResponse"];
                };
            };
        };
    };
    list_strategy_portfolios_api_portfolio_strategies_get: {
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
                    "application/json": components["schemas"]["StrategyPortfolioListResponse"];
                };
            };
        };
    };
    get_strategy_portfolio_api_portfolio_strategies__instance_id__get: {
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
                    "application/json": components["schemas"]["StrategyPortfolioDetailResponse"];
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
    get_relation_graph_api_relations_graph_get: {
        parameters: {
            query: {
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                window: number;
                min_abs_corr?: number;
                as_of?: string | null;
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
                    "application/json": components["schemas"]["RelationGraphResponse"];
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
    get_relation_neighbors_api_relations_neighbors_get: {
        parameters: {
            query: {
                product_key: string;
                bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
                window: number;
                min_abs_corr?: number;
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
                    "application/json": components["schemas"]["RelationNeighborsResponse"];
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
