// 由 `pnpm --dir frontend api:sync` 生成，勿手改。契约源：backend/contracts/openapi.json
export interface paths {
    "/api/account/equity-curve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Account Equity Curve
         * @description 按区间读权益曲线；覆盖不足时 `available=false` 且不给点，不画假线。
         */
        get: operations["get_account_equity_curve_api_account_equity_curve_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Account Summary
         * @description 最近一条账户快照；没有配置或没有快照时返回 200 与明确状态。
         */
        get: operations["get_account_summary_api_account_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/account/sync": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sync Account Snapshot
         * @description 采集一次 OKX 只读快照；上游故障返回 502，且不写半套数据。
         */
        post: operations["sync_account_snapshot_api_account_sync_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Activity
         * @description 按时间倒序返回活动流水，可按事件类型与对象类型筛选。
         */
        get: operations["get_activity_api_activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/ai/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Ai Summary
         * @description 把 BTC 市场快照与待处理提醒归纳成带来源的结构化摘要。
         */
        post: operations["post_ai_summary_api_ai_summary_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/alerts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Alerts
         * @description 按状态、类型、级别与标的筛选提醒；默认只返回待处理提醒。
         */
        get: operations["get_alerts_api_alerts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/alerts/{alert_id}": {
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
        /**
         * Patch Alert
         * @description 确认或忽略一条待处理提醒；处置结果写一条活动。
         */
        patch: operations["patch_alert_api_alerts__alert_id__patch"];
        trace?: never;
    };
    "/api/approvals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Approvals
         * @description 全部审批记录，最近写入的在前。记录只增不改，实例删除时随之级联删除。
         */
        get: operations["list_approvals_api_approvals_get"];
        put?: never;
        /**
         * Submit For Review
         * @description 提交人工审核：草稿阶段（或被驳回之后）进入待审核。
         *
         *     机会发现阶段的实例不能直接提交：转移表要求先落到草稿（`strategy_generation`），
         *     再由人工提交，否则「审核」这一步会跳过策略生成。
         */
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
        /**
         * Approve Strategy
         * @description 审核通过：进入历史回测阶段，并记下审核人与时刻。
         *
         *     回测本身由回测域执行，本端点不跑回测；`validated` 也不是这一步——它必须由达标的
         *     回测报告驱动，见 `app.strategy.approval.advance`。
         */
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
        /**
         * Authorize Live Trading
         * @description 实盘授权：记录授权事实，不打开实盘开关（开关属于执行域）。
         */
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
        /**
         * Reject Strategy
         * @description 驳回：审核没通过或回测结论不可接受时落在这里，之后只能回到草稿重走流程。
         */
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
        /**
         * List Backtests
         * @description 按数据源列出历史回测（新到旧）。数据源必填，不做跨源聚合。
         */
        get: operations["list_backtests_api_backtests_get"];
        put?: never;
        /**
         * Create Backtest
         * @description 按策略版本跑一次批量回测，每个标的各落一条运行，并返回等权组合净值。
         *
         *     版本不存在返回 404；周期与版本不一致、标的超出版本范围、类别没有对应模板都返回
         *     400。目标组合仍由现有模板引擎按同一份历史行情逐时点回放，撮合与成本模型不变。
         *     每个运行都在同一事务里写入 `strategy_linked_backtests`，历史回测因此永远指向
         *     当时那个不可变版本。
         */
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
        /**
         * Get Backtest Ranking
         * @description 按一个指标给该数据源的历史回测排序。
         *
         *     只排序，不标「最优」：把历史收益最高的那一行标成最优，等于把「过去涨得好」写成
         *     「以后也该选它」。`max_drawdown_pct` 是正数幅度，按它排序时最小的排在最前。
         */
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
        /**
         * Get Backtest
         * @description 一次回测的完整结果：组合级汇总、逐腿明细、逐笔成交与资金曲线。
         */
        get: operations["get_backtest_api_backtests__run_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Backtest
         * @description 删除一次回测及其逐笔交易与资金曲线。
         */
        delete: operations["delete_backtest_api_backtests__run_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}/chart": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Chart
         * @description K 线、买卖标记与均线叠加；标记只从 `backtest_trades` 生成。
         */
        get: operations["get_backtest_chart_api_backtests__run_id__chart_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}/equity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Equity
         * @description 策略净值与回撤序列；引擎没有保存基准行情，因此 `benchmark` 为 null。
         */
        get: operations["get_backtest_equity_api_backtests__run_id__equity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}/replay": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Replay
         * @description 按 K 线索引排列的回放点；只读本次运行保存的行情、净值与成交。
         */
        get: operations["get_backtest_replay_api_backtests__run_id__replay_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}/trades": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Backtest Trades
         * @description 按方向、盈亏结果与标的筛选交易明细，分页返回本页与总条数。
         */
        get: operations["list_backtest_trades_api_backtests__run_id__trades_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/backtests/{run_id}/trades.csv": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Backtest Trades
         * @description 导出当前筛选条件下的交易明细；UTF-8 带 BOM，列顺序固定。
         */
        get: operations["export_backtest_trades_api_backtests__run_id__trades_csv_get"];
        put?: never;
        post?: never;
        delete?: never;
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
    "/api/dashboard/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Dashboard Summary
         * @description 首页一次请求返回八个模块；单个模块失败只把它自己标成不可用。
         */
        get: operations["get_dashboard_summary_api_dashboard_summary_get"];
        put?: never;
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
    "/api/instruments/{inst_id}/analysis": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Instrument Analysis
         * @description 详情页聚合：报价、K 线、指标、关键价位、相关性、关联回测与数据覆盖。
         *
         *     业务计算全部在 `app.analysis`；这里只把值对象转换成 HTTP 契约。
         */
        get: operations["get_instrument_analysis_api_instruments__inst_id__analysis_get"];
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
         * @description 某一来源的已落库 K 线尾部窗口，附带该来源真实的可用区间与缺口标记。
         *
         *     `source` 必填、没有默认值：同一标的可能同时存有 OKX 现货与永续行情，两者的
         *     日界与计价不同，静默挑一个就把两种来源拼成一条时间轴（Q5 / D3）。缺参会由参数
         *     校验直接拒绝，不会默认成 OKX。
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
    "/api/instruments/{inst_id}/strategies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Instrument Strategies
         * @description 标的详情页的关联策略：最近一个月内有回测的，带最近一次结果。
         */
        get: operations["list_instrument_strategies_api_instruments__inst_id__strategies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/instruments/{inst_id}/sync": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sync Instrument
         * @description 接受一次单标的按需 K 线同步，立即返回，不等待上游。
         *
         *     标的未登记直接 404；周期与天数由请求模型校验。上游失败由后台任务写入
         *     `data_sync_jobs`，不会让这个接口变成 500。
         */
        post: operations["sync_instrument_api_instruments__inst_id__sync_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/macro/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Macro Overview
         * @description 首页与关注列表的宏观读数；只读库，不触发上游请求。
         */
        get: operations["get_macro_overview_api_macro_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/macro/sync": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Macro Sync
         * @description 手动刷新：同一单元正在运行或处于退避时返回 `skipped`，不排队。
         */
        post: operations["post_macro_sync_api_macro_sync_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/manual-positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Manual Positions */
        get: operations["get_manual_positions_api_manual_positions_get"];
        put?: never;
        /**
         * Create Manual Position Endpoint
         * @description 创建手动持仓并写入一条 `open` 流水；重复幂等键返回原持仓。
         */
        post: operations["create_manual_position_endpoint_api_manual_positions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/manual-positions/{position_id}": {
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
         * Delete Manual Position Endpoint
         * @description 只允许删除没有任何流水的持仓；已有流水返回 409。
         */
        delete: operations["delete_manual_position_endpoint_api_manual_positions__position_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Manual Position Endpoint
         * @description 只改止损价、杠杆与备注；数量和成本只能通过流水改变。
         */
        patch: operations["update_manual_position_endpoint_api_manual_positions__position_id__patch"];
        trace?: never;
    };
    "/api/manual-positions/{position_id}/trades": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Manual Trades
         * @description 按发生时刻倒序返回流水，带每条流水之后的持仓数量和成本。
         */
        get: operations["get_manual_trades_api_manual_positions__position_id__trades_get"];
        put?: never;
        /**
         * Add Manual Trade Endpoint
         * @description 写入手动流水；数量和成本在同一事务内更新，重复幂等键返回原流水。
         */
        post: operations["add_manual_trade_endpoint_api_manual_positions__position_id__trades_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/market/breadth": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Market Breadth
         * @description 该类别在 `as_of`（缺省为当前时刻）的涨跌家数与同向程度。
         */
        get: operations["get_market_breadth_api_market_breadth_get"];
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
        /**
         * Get Market Snapshot
         * @description BTC 与美股指数的最新值、时段、来源与报价时间；两个域各自降级。
         */
        get: operations["get_market_snapshot_api_market_overview_get"];
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
    "/api/positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Positions
         * @description OKX 与手动持仓的合并视图；`source` 可按来源过滤。
         */
        get: operations["get_positions_api_positions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/positions/cards": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Position Cards
         * @description 持仓卡片：已按未实现盈亏绝对值降序，含每条持仓的盈亏曲线与止损三态。
         *
         *     名义价值低于配置阈值的尘埃不在 `items` 里，条数由 `hidden_dust_count` 给出。
         */
        get: operations["get_position_cards_api_positions_cards_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/positions/exchange": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Exchange Positions
         * @description 最近一次同步的交易所持仓，`as_of` 与该次账户快照相同；标的未同步时返回 503。
         */
        get: operations["get_exchange_positions_api_positions_exchange_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/positions/{inst_id}/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Instrument Orders
         * @description 单标的订单历史：近 7 天与归档合并，按时间倒序。
         *
         *     上游不可用时返回 502 —— 空列表代表「确实没有订单」，不能用来表示「没查到」。
         */
        get: operations["get_instrument_orders_api_positions__inst_id__orders_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/positions/{position_ref}/risk-config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Put Position Risk Config
         * @description 保存或更新本地止损、风险预算与预警阈值。
         */
        put: operations["put_position_risk_config_api_positions__position_ref__risk_config_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/research-notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Research Notes
         * @description 按类型、关联标的/策略/回测与时间筛选研究记录。
         */
        get: operations["get_research_notes_api_research_notes_get"];
        put?: never;
        /** Post Research Note */
        post: operations["post_research_note_api_research_notes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/research-notes/{note_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Research Note */
        get: operations["get_research_note_api_research_notes__note_id__get"];
        /** Put Research Note */
        put: operations["put_research_note_api_research_notes__note_id__put"];
        post?: never;
        /** Remove Research Note */
        delete: operations["remove_research_note_api_research_notes__note_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/risk/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Risk Event Records */
        get: operations["list_risk_event_records_api_risk_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/risk/events/{event_id}/resolve": {
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
        /** Resolve Risk Event Record */
        patch: operations["resolve_risk_event_record_api_risk_events__event_id__resolve_patch"];
        trace?: never;
    };
    "/api/risk/exposure": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Risk Exposure
         * @description 组合风险与敞口：多空名义价值、行业分布、止损距离与规则结果。
         */
        get: operations["get_risk_exposure_api_risk_exposure_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/risk/notify-config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Risk Notify Config
         * @description 五条风控通知规则：开关、渠道与阈值。
         */
        get: operations["get_risk_notify_config_api_risk_notify_config_get"];
        /**
         * Put Risk Notify Config
         * @description 保存通知规则；只影响通知与评估开关，不改变持仓页上的数字。
         */
        put: operations["put_risk_notify_config_api_risk_notify_config_put"];
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
        /**
         * Get Settings Document
         * @description 当前设置：显示偏好、风险默认值、执行开关、数据源与密钥状态。
         */
        get: operations["get_settings_document_api_settings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Patch Settings Document
         * @description 按分组部分更新；未提交的分组保持原值。
         */
        patch: operations["patch_settings_document_api_settings_patch"];
        trace?: never;
    };
    "/api/settings/notifications/deliveries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Notification Deliveries
         * @description 最近若干条投递记录，新的在前。
         */
        get: operations["get_notification_deliveries_api_settings_notifications_deliveries_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/settings/notifications/test": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Test Notification Channel
         * @description 用同一个通道实现投一条测试事件，并把这次投递写进台账。
         */
        post: operations["test_notification_channel_api_settings_notifications_test_post"];
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
        /**
         * List Strategies Endpoint
         * @description 用户策略列表：当前版本、状态、标的数量与最近回测摘要。
         */
        get: operations["list_strategies_endpoint_api_strategies_get"];
        put?: never;
        /**
         * Create Strategy Endpoint
         * @description 创建策略与第一个草稿版本。
         */
        post: operations["create_strategy_endpoint_api_strategies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategies/runtime": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Strategy Runtime
         * @description 策略页运行状态：扫描未实现、自动执行开关与后端检查时间。
         */
        get: operations["get_strategy_runtime_api_strategies_runtime_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategies/{strategy_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Strategy Endpoint
         * @description 策略详情：当前版本、参数、标的、版本目录与最近回测。
         */
        get: operations["get_strategy_endpoint_api_strategies__strategy_id__get"];
        /**
         * Update Strategy Endpoint
         * @description 只改元数据时原地更新；提交任一版本字段时新建下一版。
         */
        put: operations["update_strategy_endpoint_api_strategies__strategy_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategies/{strategy_id}/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Strategy Versions */
        get: operations["list_strategy_versions_api_strategies__strategy_id__versions_get"];
        put?: never;
        /**
         * Create Strategy Version
         * @description 新建下一版；未提交的字段沿用当前版本。旧版本不提供修改入口。
         */
        post: operations["create_strategy_version_api_strategies__strategy_id__versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/strategies/{strategy_id}/versions/{version}/instruments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Strategy Version Instruments
         * @description 整批替换当前版本的标的集合；旧版本返回 409。
         */
        put: operations["update_strategy_version_instruments_api_strategies__strategy_id__versions__version__instruments_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/system/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Health
         * @description 数据库、OKX REST、OKX WebSocket、任务队列、K 线覆盖、宏观与美股渠道。
         */
        get: operations["get_system_health_api_system_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/system/sync": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post System Sync
         * @description 手动触发一次 OKX 数据同步；同一数据集已在运行时返回 409。
         */
        post: operations["post_system_sync_api_system_sync_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
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
         * @description 按加入顺序返回全部自选条目、分组名，以及关联策略与最近信号。
         *
         *     策略与信号由本层从 `strategy` / `execution` 门面组合：`watchlist` 域本身不依赖
         *     这两个模块，列表行的行情口径仍由 `app.watchlist` 单独负责。
         */
        get: operations["list_watchlist_api_watchlist_get"];
        put?: never;
        /**
         * Add Watchlist Item
         * @description 把标的加入自选；只要求标的已同步，行情缺失时按 `data_status` 返回。
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
        /**
         * AccountSummaryResponse
         * @description 账户卡：最近一条账户快照，以及只在北京时间日初有基准时给出的今日盈亏。
         * @example {
         *       "account_id": "okx-main",
         *       "available_equity": "682.30",
         *       "available_margin": "682.30",
         *       "captured_at": "2026-11-13T09:00:00Z",
         *       "cash_balance": "0",
         *       "currency": "USDT",
         *       "day_pnl_basis": "equity_only",
         *       "equity": "1248.60",
         *       "gross_notional": "1851.36",
         *       "margin_usage_floor": false,
         *       "margin_usage_pct": "45.36",
         *       "margin_used": "617.12",
         *       "net_notional": "1851.36",
         *       "notional_status": "exact",
         *       "position_notional": "1851.36",
         *       "position_notional_at": "2026-11-13T09:00:00Z",
         *       "source": "okx_rest",
         *       "status": "ok",
         *       "unrealized_pnl": "31.84",
         *       "used_margin": "566.30"
         *     }
         */
        AccountSummaryResponse: {
            /** Account Id */
            account_id: string;
            /** Available Equity */
            available_equity?: string | null;
            /** Available Margin */
            available_margin?: string | null;
            /** Captured At */
            captured_at?: string | null;
            /** Cash Balance */
            cash_balance?: string | null;
            /** Currency */
            currency: string;
            /** Day Pnl */
            day_pnl?: string | null;
            /**
             * Day Pnl Basis
             * @default equity_only
             * @constant
             */
            day_pnl_basis: "equity_only";
            /** Equity */
            equity?: string | null;
            /** Gross Notional */
            gross_notional?: string | null;
            /**
             * Margin Usage Floor
             * @default true
             */
            margin_usage_floor: boolean;
            /** Margin Usage Pct */
            margin_usage_pct?: string | null;
            /** Margin Used */
            margin_used?: string | null;
            /** Net Notional */
            net_notional?: string | null;
            /**
             * Notional Status
             * @default partial
             * @enum {string}
             */
            notional_status: "exact" | "partial";
            /** Position Notional */
            position_notional?: string | null;
            /** Position Notional At */
            position_notional_at?: string | null;
            /** Source */
            source?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unconfigured";
            /** Unrealized Pnl */
            unrealized_pnl?: string | null;
            /** Used Margin */
            used_margin?: string | null;
        };
        /**
         * AccountSyncResponse
         * @description 一次同步的结果：账户卡 + 本次写入的持仓条数。
         * @example {
         *       "account_id": "okx-main",
         *       "available_equity": "682.30",
         *       "available_margin": "682.30",
         *       "captured_at": "2026-11-13T09:00:00Z",
         *       "cash_balance": "0",
         *       "currency": "USDT",
         *       "day_pnl_basis": "equity_only",
         *       "equity": "1248.60",
         *       "gross_notional": "1851.36",
         *       "margin_usage_floor": false,
         *       "margin_usage_pct": "45.36",
         *       "margin_used": "617.12",
         *       "net_notional": "1851.36",
         *       "notional_status": "exact",
         *       "position_notional": "1851.36",
         *       "position_notional_at": "2026-11-13T09:00:00Z",
         *       "positions_synced": 1,
         *       "source": "okx_rest",
         *       "status": "ok",
         *       "unrealized_pnl": "31.84",
         *       "used_margin": "566.30"
         *     }
         */
        AccountSyncResponse: {
            /** Account Id */
            account_id: string;
            /** Available Equity */
            available_equity?: string | null;
            /** Available Margin */
            available_margin?: string | null;
            /** Captured At */
            captured_at?: string | null;
            /** Cash Balance */
            cash_balance?: string | null;
            /** Currency */
            currency: string;
            /** Day Pnl */
            day_pnl?: string | null;
            /**
             * Day Pnl Basis
             * @default equity_only
             * @constant
             */
            day_pnl_basis: "equity_only";
            /** Equity */
            equity?: string | null;
            /** Gross Notional */
            gross_notional?: string | null;
            /**
             * Margin Usage Floor
             * @default true
             */
            margin_usage_floor: boolean;
            /** Margin Usage Pct */
            margin_usage_pct?: string | null;
            /** Margin Used */
            margin_used?: string | null;
            /** Net Notional */
            net_notional?: string | null;
            /**
             * Notional Status
             * @default partial
             * @enum {string}
             */
            notional_status: "exact" | "partial";
            /** Position Notional */
            position_notional?: string | null;
            /** Position Notional At */
            position_notional_at?: string | null;
            /** Positions Synced */
            positions_synced: number;
            /** Source */
            source?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unconfigured";
            /** Unrealized Pnl */
            unrealized_pnl?: string | null;
            /** Used Margin */
            used_margin?: string | null;
        };
        /**
         * ActivityItem
         * @example {
         *       "created_at": "2026-11-10T23:00:00Z",
         *       "event_type": "research_note.created",
         *       "id": "ac_0001",
         *       "object_id": "rn_0001",
         *       "object_type": "research_note",
         *       "payload": {
         *         "type": "hypothesis"
         *       },
         *       "summary": "创建研究记录「AAPL 假设」"
         *     }
         */
        ActivityItem: {
            /** Created At */
            created_at: string;
            /** Event Type */
            event_type: string;
            /** Id */
            id: string;
            /** Object Id */
            object_id: string;
            /** Object Type */
            object_type: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Summary */
            summary: string;
        };
        /**
         * ActivityListResponse
         * @example {
         *       "items": [
         *         {
         *           "created_at": "2026-11-10T23:00:00Z",
         *           "event_type": "research_note.created",
         *           "id": "ac_0001",
         *           "object_id": "rn_0001",
         *           "object_type": "research_note",
         *           "payload": {
         *             "type": "hypothesis"
         *           },
         *           "summary": "创建研究记录「AAPL 假设」"
         *         }
         *       ]
         *     }
         */
        ActivityListResponse: {
            /** Items */
            items: components["schemas"]["ActivityItem"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /**
         * AiSummaryPoint
         * @description 摘要里的一个事实点；`sources` 至少一条。
         */
        AiSummaryPoint: {
            /** Sources */
            sources: components["schemas"]["AiSummarySource"][];
            /** Text */
            text: string;
        };
        /**
         * AiSummaryResponse
         * @description 结构化摘要；没有来源的事实点不会出现在 `points` 或 `risks` 里。
         * @example {
         *       "disclaimer": "仅作信息归纳，不构成交易建议",
         *       "generated_at": "2026-11-15T06:10:00Z",
         *       "overall": "偏强",
         *       "points": [
         *         {
         *           "sources": [
         *             {
         *               "id": "BTC",
         *               "type": "market_overview"
         *             }
         *           ],
         *           "text": "Bitcoin 最新 65000.5，较前值 +1.88%。"
         *         }
         *       ],
         *       "risks": [
         *         {
         *           "sources": [
         *             {
         *               "id": "alert_0123456789abcdef01234567",
         *               "type": "alert"
         *             }
         *           ],
         *           "text": "持仓缺少止损：AAPL-USDT-SWAP"
         *         }
         *       ],
         *       "stale": false
         *     }
         */
        AiSummaryResponse: {
            /** Disclaimer */
            disclaimer: string;
            /** Generated At */
            generated_at: string;
            /** Overall */
            overall: string;
            /** Points */
            points: components["schemas"]["AiSummaryPoint"][];
            /** Risks */
            risks: components["schemas"]["AiSummaryPoint"][];
            /** Stale */
            stale: boolean;
            /** Stale Notice */
            stale_notice?: string | null;
        };
        /**
         * AiSummarySource
         * @description 一条可回溯的来源；`id` 对应指标或提醒的本地标识。
         */
        AiSummarySource: {
            /** Id */
            id: string;
            /**
             * Type
             * @enum {string}
             */
            type: "alert" | "market_overview" | "risk";
            /** Url */
            url?: string | null;
        };
        /**
         * AlertItem
         * @example {
         *       "detail": "XAAPL-USDT 没有有效止损记录",
         *       "id": "al_0001",
         *       "instrument_id": "XAAPL-USDT",
         *       "payload": {
         *         "position_ref": "manual:0001"
         *       },
         *       "rule_id": "stop_missing",
         *       "rule_version": "b3-exposure-v1",
         *       "severity": "warning",
         *       "status": "pending",
         *       "title": "持仓缺少止损",
         *       "triggered_at": "2026-11-10T23:00:00Z",
         *       "type": "risk"
         *     }
         */
        AlertItem: {
            /** Detail */
            detail: string;
            /** Expires At */
            expires_at?: string | null;
            /** Id */
            id: string;
            /** Instrument Id */
            instrument_id?: string | null;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Rule Id */
            rule_id: string;
            /** Rule Version */
            rule_version?: string | null;
            /**
             * Severity
             * @enum {string}
             */
            severity: "info" | "warning" | "critical";
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "acknowledged" | "ignored" | "expired";
            /** Title */
            title: string;
            /** Triggered At */
            triggered_at: string;
            /**
             * Type
             * @enum {string}
             */
            type: "indicator" | "price" | "risk" | "strategy" | "data" | "market" | "watchlist";
        };
        /**
         * AlertListResponse
         * @example {
         *       "items": [
         *         {
         *           "detail": "XAAPL-USDT 没有有效止损记录",
         *           "id": "al_0001",
         *           "instrument_id": "XAAPL-USDT",
         *           "payload": {
         *             "position_ref": "manual:0001"
         *           },
         *           "rule_id": "stop_missing",
         *           "rule_version": "b3-exposure-v1",
         *           "severity": "warning",
         *           "status": "pending",
         *           "title": "持仓缺少止损",
         *           "triggered_at": "2026-11-10T23:00:00Z",
         *           "type": "risk"
         *         }
         *       ]
         *     }
         */
        AlertListResponse: {
            /** Items */
            items: components["schemas"]["AlertItem"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /** AlertStatusUpdateRequest */
        AlertStatusUpdateRequest: {
            /**
             * Status
             * @enum {string}
             */
            status: "acknowledged" | "ignored";
        };
        /** AnalysisCandles */
        AnalysisCandles: {
            /** Available From */
            available_from?: string | null;
            /** Available To */
            available_to?: string | null;
            /** Candles */
            candles: components["schemas"]["Candle"][];
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Gaps */
            gaps: components["schemas"]["AnalysisGap"][];
            /** Overlays */
            overlays: components["schemas"]["AnalysisOverlay"][];
        };
        /** AnalysisCoverage */
        AnalysisCoverage: {
            /** Available */
            available: boolean;
            /** Available From */
            available_from?: string | null;
            /** Available To */
            available_to?: string | null;
            /**
             * Bar
             * @enum {string}
             */
            bar: "1d" | "4h" | "1h";
            /** Candle Count */
            candle_count: number;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Gap Count */
            gap_count: number;
            /** Last Synced At */
            last_synced_at?: string | null;
            /** Unavailable Reason */
            unavailable_reason?: string | null;
        };
        /** AnalysisGap */
        AnalysisGap: {
            /** End */
            end: string;
            /** Missing */
            missing: number;
            /** Start */
            start: string;
        };
        /** AnalysisIndicators */
        AnalysisIndicators: {
            momentum: components["schemas"]["MomentumIndicators"];
            /** Readings */
            readings: string[];
            relative_strength: components["schemas"]["RelativeStrengthIndicators"];
            trend: components["schemas"]["TrendIndicators"];
            volatility: components["schemas"]["VolatilityIndicators"];
            volume: components["schemas"]["VolumeIndicators"];
        };
        /** AnalysisLevels */
        AnalysisLevels: {
            /** High20 */
            high20?: string | null;
            /** High Distance Pct */
            high_distance_pct?: string | null;
            /** Low20 */
            low20?: string | null;
            /** Low Distance Pct */
            low_distance_pct?: string | null;
            /** Window */
            window: number;
        };
        /** AnalysisOverlay */
        AnalysisOverlay: {
            /** Name */
            name: string;
            /** Points */
            points: components["schemas"]["AnalysisOverlayPoint"][];
        };
        /** AnalysisOverlayPoint */
        AnalysisOverlayPoint: {
            /** Time */
            time: string;
            /** Value */
            value: string;
        };
        /**
         * AnalysisPrice
         * @description 一种价格语义；`last` / `mark` / `index` 各自独立，缺失时整个对象为 null。
         */
        AnalysisPrice: {
            /** As Of */
            as_of: string;
            /** Change */
            change?: string | null;
            /** Change Pct */
            change_pct?: string | null;
            /** Price */
            price: string;
            /**
             * Source
             * @enum {string}
             */
            source: "okx" | "okx_spot" | "okx_swap";
        };
        /** AnalysisQuote */
        AnalysisQuote: {
            index?: components["schemas"]["AnalysisPrice"] | null;
            last?: components["schemas"]["AnalysisPrice"] | null;
            mark?: components["schemas"]["AnalysisPrice"] | null;
        };
        /**
         * BacktestBatchResponse
         * @description 批量回测的创建结果：第一条运行的汇总 + 全部运行标识 + 等权组合净值。
         * @example {
         *       "bar": "1h",
         *       "combination": "equal_weight",
         *       "combination_note": "各成员运行按首点归一化后的净值等权平均；缺失时沿用上一有效点",
         *       "created_at": "2026-11-10T01:20:00Z",
         *       "data_source": "okx",
         *       "end_date": "2026-11-01",
         *       "finished_at": "2026-11-10T01:21:30Z",
         *       "group_equity": [
         *         {
         *           "nav": "1",
         *           "time": "2026-11-05T00:00:00Z"
         *         },
         *         {
         *           "nav": "1.004",
         *           "time": "2026-11-06T00:00:00Z"
         *         }
         *       ],
         *       "inst_id": "XAAPL-USDT",
         *       "inst_type": "SPOT",
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
         *       "params": {
         *         "pair_count": 1,
         *         "reversion_window": 3,
         *         "strength_window": 2
         *       },
         *       "run_id": "bt_0001",
         *       "run_ids": [
         *         "bt_0001",
         *         "bt_0002"
         *       ],
         *       "start_date": "2026-08-01",
         *       "status": "succeeded",
         *       "strategy_version_id": "sv_0001",
         *       "symbol_count": 1
         *     }
         */
        BacktestBatchResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /**
             * Combination
             * @default equal_weight
             * @constant
             */
            combination: "equal_weight";
            /**
             * Combination Note
             * @default 各成员运行按首点归一化后的净值等权平均；缺失时沿用上一有效点
             */
            combination_note: string;
            /** Created At */
            created_at: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /**
             * End Date
             * Format: date
             */
            end_date: string;
            /** Error Message */
            error_message?: string | null;
            /** Finished At */
            finished_at?: string | null;
            /** Group Equity */
            group_equity: components["schemas"]["GroupEquityPoint"][];
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            metrics?: components["schemas"]["BacktestMetrics"] | null;
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
            /** Run Id */
            run_id: string;
            /** Run Ids */
            run_ids: string[];
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
            /** Strategy Version Id */
            strategy_version_id: string | null;
            /** Symbol Count */
            symbol_count: number;
        };
        /**
         * BacktestChartCandle
         * @description 回测 K 线：只包含本次运行实际用到的 bar，来源与是否收盘原样保留。
         */
        BacktestChartCandle: {
            /** Close */
            close: string;
            /** High */
            high: string;
            /** Is Complete */
            is_complete: boolean;
            /** Low */
            low: string;
            /** Open */
            open: string;
            /**
             * Source
             * @enum {string}
             */
            source: "okx" | "okx_spot" | "okx_swap";
            /** Time */
            time: string;
            /** Volume */
            volume: string;
        };
        /**
         * BacktestChartResponse
         * @description K 线图：K 线、来自成交表的买卖标记、由已保存行情算出的均线叠加。
         * @example {
         *       "bar": "1d",
         *       "candles": [
         *         {
         *           "close": "103",
         *           "high": "104",
         *           "is_complete": true,
         *           "low": "99",
         *           "open": "100",
         *           "source": "okx",
         *           "time": "2026-11-05T00:00:00Z",
         *           "volume": "1200"
         *         }
         *       ],
         *       "data_source": "okx",
         *       "inst_id": "XAAPL-USDT",
         *       "markers": [
         *         {
         *           "kind": "entry",
         *           "price": "101",
         *           "qty": "8.63",
         *           "side": "buy",
         *           "time": "2026-11-06T00:00:00Z",
         *           "trade_id": "tr_0001"
         *         },
         *         {
         *           "kind": "exit",
         *           "pnl": "17.26",
         *           "price": "103",
         *           "qty": "8.63",
         *           "reason": "MA20 下穿 MA60",
         *           "side": "sell",
         *           "time": "2026-11-08T00:00:00Z",
         *           "trade_id": "tr_0001"
         *         }
         *       ],
         *       "overlays": [
         *         {
         *           "name": "MA20",
         *           "points": [
         *             {
         *               "time": "2026-11-05T00:00:00Z",
         *               "value": "98.40"
         *             }
         *           ]
         *         }
         *       ],
         *       "run_id": "bt_0001"
         *     }
         */
        BacktestChartResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Candles */
            candles: components["schemas"]["BacktestChartCandle"][];
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Inst Id */
            inst_id: string;
            /** Markers */
            markers: components["schemas"]["BacktestMarker"][];
            /** Overlays */
            overlays: components["schemas"]["BacktestOverlay"][];
            /** Run Id */
            run_id: string;
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
         * @description 一次回测的完整结果：组合级汇总在上，逐腿明细在下。
         *
         *     `trades` 是逐笔成交（每笔完整交易的开平仓时刻、价格、成本与盈亏），`legs` 是按
         *     `product_key` 与方向汇总后的逐腿明细，`equity_curve` 是逐 bar 的资金曲线。
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
         *       "legs": [
         *         {
         *           "contribution_pct": "2.4055",
         *           "entry_time": "2026-08-04T14:00:00Z",
         *           "exit_time": "2026-10-28T06:00:00Z",
         *           "fee": "18.40",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "pnl": "240.55",
         *           "product_key": "XAAPL",
         *           "side": "long",
         *           "trade_count": 37
         *         }
         *       ],
         *       "portfolio": {
         *         "leg_win_rate": {
         *           "XAAPL": "0.54"
         *         },
         *         "long_pnl": "210.45",
         *         "net_exposure": "0.5",
         *         "short_pnl": "-18.20"
         *       },
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
         *         "strategy_version_id": "sv_0001",
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
         *         "inst_id": "XAAPL-USDT",
         *         "inst_type": "SPOT",
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
         *         "params": {
         *           "pair_count": 1,
         *           "reversion_window": 3,
         *           "strength_window": 2
         *         },
         *         "run_id": "bt_0001",
         *         "start_date": "2026-08-01",
         *         "status": "succeeded",
         *         "strategy_version_id": "sv_0001",
         *         "symbol_count": 1
         *       },
         *       "trades": [
         *         {
         *           "entry_price": "228.10",
         *           "entry_time": "2026-08-04T14:00:00Z",
         *           "exit_price": "232.44",
         *           "exit_time": "2026-08-05T06:00:00Z",
         *           "fee": "1.98",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "net_pnl": "33.26",
         *           "pnl": "35.24",
         *           "product_key": "XAAPL",
         *           "qty": "8.63",
         *           "reason": "MA20 下穿 MA60",
         *           "side": "long",
         *           "slippage": "0.42",
         *           "trade_id": "tr_0001"
         *         }
         *       ]
         *     }
         */
        BacktestDetailResponse: {
            /** Equity Curve */
            equity_curve: components["schemas"]["EquityPoint"][];
            /** Legs */
            legs: components["schemas"]["BacktestLeg"][];
            portfolio: components["schemas"]["BacktestPortfolio"];
            request: components["schemas"]["BacktestRequest"];
            run: components["schemas"]["BacktestRunSummary"];
            /** Trades */
            trades: components["schemas"]["BacktestTrade"][];
        };
        /**
         * BacktestEquityPoint
         * @description 净值曲线的一个点；`benchmark_equity` 缺失时保持 null，不补假线。
         */
        BacktestEquityPoint: {
            /** Benchmark Equity */
            benchmark_equity?: string | null;
            /** Drawdown */
            drawdown: string;
            /** Equity */
            equity: string;
            /** Time */
            time: string;
        };
        /**
         * BacktestEquityResponse
         * @example {
         *       "points": [
         *         {
         *           "drawdown": "0",
         *           "equity": "10000",
         *           "time": "2026-11-05T00:00:00Z"
         *         },
         *         {
         *           "drawdown": "-0.006",
         *           "equity": "9940",
         *           "time": "2026-11-06T00:00:00Z"
         *         }
         *       ],
         *       "run_id": "bt_0001"
         *     }
         */
        BacktestEquityResponse: {
            /** Benchmark */
            benchmark?: string | null;
            /** Points */
            points: components["schemas"]["BacktestEquityPoint"][];
            /** Run Id */
            run_id: string;
        };
        /**
         * BacktestLeg
         * @description 一条腿在本次回测里的汇总：方向、第一笔开仓到最后一笔平仓、成本与贡献。
         *
         *     `contribution_pct` 是这条腿的**已实现**盈亏占初始资金的百分比。回测结束时仍未
         *     平掉的仓位只体现在资金曲线里，不在逐腿明细里，因此全部腿的贡献相加可能小于总收益率
         *     ——差的正是未平仓部分的浮动盈亏。
         */
        BacktestLeg: {
            /** Contribution Pct */
            contribution_pct: string;
            /** Entry Time */
            entry_time: string;
            /** Exit Time */
            exit_time: string;
            /** Fee */
            fee: string;
            /** Funding */
            funding?: string | null;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Pnl */
            pnl: string;
            /** Product Key */
            product_key: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /** Trade Count */
            trade_count: number;
        };
        /**
         * BacktestMarker
         * @description 一笔完整交易的入场或出场标记；每个标记都来自 `backtest_trades` 的一行。
         */
        BacktestMarker: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "entry" | "exit";
            /** Pnl */
            pnl?: string | null;
            /** Price */
            price: string;
            /** Qty */
            qty: string;
            /** Reason */
            reason?: string | null;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
            /** Time */
            time: string;
            /** Trade Id */
            trade_id: string;
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
        /** BacktestOverlay */
        BacktestOverlay: {
            /** Name */
            name: string;
            /** Points */
            points: components["schemas"]["BacktestOverlayPoint"][];
        };
        /** BacktestOverlayPoint */
        BacktestOverlayPoint: {
            /** Time */
            time: string;
            /** Value */
            value: string;
        };
        /**
         * BacktestPortfolio
         * @description 组合级汇总：净敞口、每腿胜率、多腿与空腿的合计盈亏。
         *
         *     逐腿明细在 `BacktestDetailResponse.legs`：这里只回答「整个组合怎么样」，
         *     单条腿各自赚了多少放在下面那张表里。
         */
        BacktestPortfolio: {
            /** Leg Win Rate */
            leg_win_rate: {
                [key: string]: string;
            };
            /** Long Pnl */
            long_pnl: string;
            /** Net Exposure */
            net_exposure: string;
            /** Short Pnl */
            short_pnl: string;
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
         *           "params": {
         *             "pair_count": 1,
         *             "reversion_window": 3,
         *             "strength_window": 2
         *           },
         *           "profit_factor": "1.95",
         *           "run_id": "bt_0001",
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
            data_source: "okx" | "okx_spot" | "okx_swap";
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
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
            /** Profit Factor */
            profit_factor: string;
            /** Run Id */
            run_id: string;
            /** Sharpe */
            sharpe: string;
            /** Total Return Pct */
            total_return_pct: string;
            /** Trade Count */
            trade_count: number;
        };
        /**
         * BacktestReplayPoint
         * @description 按 K 线索引排列的一个回放点；全部字段来自已保存的行情与结果。
         */
        BacktestReplayPoint: {
            /** Cash */
            cash: string;
            /** Close */
            close?: string | null;
            /** Equity */
            equity: string;
            /** Index */
            index: number;
            /** Indicators */
            indicators: {
                [key: string]: string | null;
            };
            /** Position */
            position: string;
            /**
             * Signal
             * @enum {string}
             */
            signal: "BUY" | "SELL" | "HOLD";
            /** Time */
            time: string;
        };
        /**
         * BacktestReplayResponse
         * @example {
         *       "bar": "1d",
         *       "points": [
         *         {
         *           "cash": "10000",
         *           "close": "103",
         *           "equity": "10000",
         *           "index": 0,
         *           "indicators": {
         *             "ma20": "98.40"
         *           },
         *           "position": "0",
         *           "signal": "HOLD",
         *           "time": "2026-11-05T00:00:00Z"
         *         },
         *         {
         *           "cash": "9128.37",
         *           "close": "101",
         *           "equity": "10020",
         *           "index": 1,
         *           "indicators": {
         *             "ma20": "99.10",
         *             "ma60": "96.80"
         *           },
         *           "position": "891.63",
         *           "signal": "BUY",
         *           "time": "2026-11-06T00:00:00Z"
         *         }
         *       ],
         *       "run_id": "bt_0001",
         *       "trades": [
         *         {
         *           "index": 1,
         *           "kind": "entry",
         *           "price": "101",
         *           "qty": "8.63",
         *           "side": "buy",
         *           "trade_id": "tr_0001"
         *         }
         *       ]
         *     }
         */
        BacktestReplayResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Points */
            points: components["schemas"]["BacktestReplayPoint"][];
            /** Run Id */
            run_id: string;
            /** Trades */
            trades: components["schemas"]["BacktestReplayTrade"][];
        };
        /**
         * BacktestReplayTrade
         * @description 回放时间轴上的成交事件；`index` 与该运行第几根 K 线对应。
         */
        BacktestReplayTrade: {
            /** Index */
            index: number;
            /**
             * Kind
             * @enum {string}
             */
            kind: "entry" | "exit";
            /** Price */
            price: string;
            /** Qty */
            qty: string;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
            /** Trade Id */
            trade_id: string;
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
            data_source: "okx" | "okx_spot" | "okx_swap";
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
            /** Strategy Version Id */
            strategy_version_id: string;
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
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
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
         *           "params": {
         *             "pair_count": 1,
         *             "reversion_window": 3,
         *             "strength_window": 2
         *           },
         *           "run_id": "bt_0001",
         *           "start_date": "2026-08-01",
         *           "status": "succeeded",
         *           "strategy_version_id": "sv_0001",
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
            data_source: "okx" | "okx_spot" | "okx_swap";
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
         *       "inst_id": "XAAPL-USDT",
         *       "inst_type": "SPOT",
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
         *       "params": {
         *         "pair_count": 1,
         *         "reversion_window": 3,
         *         "strength_window": 2
         *       },
         *       "run_id": "bt_0001",
         *       "start_date": "2026-08-01",
         *       "status": "succeeded",
         *       "strategy_version_id": "sv_0001",
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
            data_source: "okx" | "okx_spot" | "okx_swap";
            /**
             * End Date
             * Format: date
             */
            end_date: string;
            /** Error Message */
            error_message?: string | null;
            /** Finished At */
            finished_at?: string | null;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            metrics?: components["schemas"]["BacktestMetrics"] | null;
            /** Params */
            params: {
                [key: string]: number | string | boolean;
            };
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
            /** Strategy Version Id */
            strategy_version_id: string | null;
            /** Symbol Count */
            symbol_count: number;
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
            data_source: "okx" | "okx_spot" | "okx_swap";
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
            funding?: string | null;
            /** Inst Id */
            inst_id: string;
            /**
             * Inst Type
             * @enum {string}
             */
            inst_type: "SPOT" | "SWAP";
            /** Net Pnl */
            net_pnl: string;
            /** Pnl */
            pnl: string;
            /** Product Key */
            product_key: string;
            /** Qty */
            qty: string;
            /** Reason */
            reason: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /** Slippage */
            slippage: string;
            /** Trade Id */
            trade_id: string;
        };
        /**
         * BacktestTradeListResponse
         * @example {
         *       "items": [
         *         {
         *           "entry_price": "101",
         *           "entry_time": "2026-11-06T00:00:00Z",
         *           "exit_price": "103",
         *           "exit_time": "2026-11-08T00:00:00Z",
         *           "fee": "0.87",
         *           "inst_id": "XAAPL-USDT",
         *           "inst_type": "SPOT",
         *           "net_pnl": "16.39",
         *           "pnl": "17.26",
         *           "product_key": "XAAPL",
         *           "qty": "8.63",
         *           "reason": "MA20 下穿 MA60",
         *           "side": "long",
         *           "slippage": "0.44",
         *           "trade_id": "tr_0001"
         *         }
         *       ],
         *       "limit": 100,
         *       "offset": 0,
         *       "run_id": "bt_0001",
         *       "total": 1
         *     }
         */
        BacktestTradeListResponse: {
            /** Items */
            items: components["schemas"]["BacktestTrade"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Run Id */
            run_id: string;
            /** Total */
            total: number;
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
            data_source: "okx" | "okx_spot" | "okx_swap";
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
            data_source: "okx" | "okx_spot" | "okx_swap";
            /**
             * Has Gap
             * @default false
             */
            has_gap: boolean;
            /** Inst Id */
            inst_id: string;
        };
        /**
         * ChannelSubscriptionSettings
         * @description 一个通道的订阅：收哪几类提醒、最低到什么严重度才收。
         */
        ChannelSubscriptionSettings: {
            /**
             * Min Severity
             * @default info
             * @enum {string}
             */
            min_severity: "info" | "warning" | "critical";
            /** Types */
            types?: string[];
        };
        /**
         * ChannelSubscriptionUpdate
         * @description 一个通道的订阅写入：只覆盖提交出来的字段，未提交的字段保持库中原值。
         */
        ChannelSubscriptionUpdate: {
            /** Min Severity */
            min_severity?: ("info" | "warning" | "critical") | null;
            /** Types */
            types?: string[] | null;
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
        /** CorrelationReading */
        CorrelationReading: {
            /** Coefficient */
            coefficient?: string | null;
            /** Inst Id */
            inst_id: string;
            /** Product Key */
            product_key: string;
            /**
             * Role
             * @enum {string}
             */
            role: "benchmark" | "related";
            /** Sample Size */
            sample_size: number;
            /** Window */
            window: number;
            /** Window End */
            window_end?: string | null;
            /** Window Start */
            window_start?: string | null;
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
        /**
         * CurvePointItem
         * @description 曲线上的一个点；`value` 是该时刻的快照值，不做插值。
         */
        CurvePointItem: {
            /** At */
            at: string;
            /** Value */
            value: string;
        };
        /**
         * DashboardAccountData
         * @description 账户卡内容；派生字段由 `app.positions` 给出，聚合层不重算。
         */
        DashboardAccountData: {
            /** Account Id */
            account_id: string;
            /** Available Equity */
            available_equity?: string | null;
            /** Available Margin */
            available_margin?: string | null;
            /** Captured At */
            captured_at?: string | null;
            /** Cash Balance */
            cash_balance?: string | null;
            /** Currency */
            currency: string;
            /** Day Pnl */
            day_pnl?: string | null;
            /**
             * Day Pnl Basis
             * @default equity_only
             * @constant
             */
            day_pnl_basis: "equity_only";
            /** Equity */
            equity?: string | null;
            /** Margin Usage Pct */
            margin_usage_pct?: string | null;
            /** Source */
            source?: string | null;
            /** Unrealized Pnl */
            unrealized_pnl?: string | null;
            /** Used Margin */
            used_margin?: string | null;
        };
        /** DashboardAccountModule */
        DashboardAccountModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardAccountData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /** DashboardActivityItem */
        DashboardActivityItem: {
            /** Created At */
            created_at: string;
            /** Event Type */
            event_type: string;
            /** Id */
            id: string;
            /** Object Id */
            object_id: string;
            /** Object Type */
            object_type: string;
            /** Summary */
            summary: string;
        };
        /** DashboardActivityModule */
        DashboardActivityModule: {
            /** As Of */
            as_of?: string | null;
            /** Data */
            data?: components["schemas"]["DashboardActivityItem"][] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /**
         * DashboardAlertItem
         * @description 待处理提醒；来源是提醒事件表。
         */
        DashboardAlertItem: {
            /** Detail */
            detail: string;
            /** Id */
            id: string;
            /** Instrument Id */
            instrument_id?: string | null;
            /** Rule Id */
            rule_id: string;
            /** Severity */
            severity?: string | null;
            /**
             * Status
             * @constant
             */
            status: "pending";
            /** Title */
            title: string;
            /** Triggered At */
            triggered_at: string;
            /**
             * Type
             * @enum {string}
             */
            type: "indicator" | "price" | "risk" | "strategy" | "data" | "market" | "watchlist";
        };
        /** DashboardAlertsModule */
        DashboardAlertsModule: {
            /** As Of */
            as_of?: string | null;
            /** Data */
            data?: components["schemas"]["DashboardAlertItem"][] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /** DashboardDegradedItem */
        DashboardDegradedItem: {
            /** Last Success At */
            last_success_at?: string | null;
            /** Module */
            module: string;
            /** Reason */
            reason: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /** DashboardMarketData */
        DashboardMarketData: {
            /** Items */
            items: components["schemas"]["DashboardMarketItem"][];
            /**
             * Session
             * @enum {string}
             */
            session: "pre" | "regular" | "post" | "closed";
        };
        /**
         * DashboardMarketItem
         * @description 一个标的类别在首页上的市场状态、广度与共振。
         */
        DashboardMarketItem: {
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
            /**
             * Primary Source
             * @enum {string}
             */
            primary_source: "okx" | "okx_spot" | "okx_swap";
            resonance: components["schemas"]["MarketResonance"];
            /**
             * Session
             * @enum {string}
             */
            session: "pre" | "regular" | "post" | "closed";
        };
        /** DashboardMarketModule */
        DashboardMarketModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardMarketData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /**
         * DashboardPositionItem
         * @description 首页持仓行：只保留展示需要的字段，完整明细走各自的域接口。
         */
        DashboardPositionItem: {
            /** Display Symbol */
            display_symbol: string;
            /** Inst Id */
            inst_id: string;
            /** Leverage */
            leverage?: string | null;
            /** Mark Price */
            mark_price?: string | null;
            /** Notional */
            notional?: string | null;
            /** Position Ref */
            position_ref: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /**
             * Source
             * @enum {string}
             */
            source: "exchange" | "manual";
            /** Stop Distance Pct */
            stop_distance_pct?: string | null;
            /** Unrealized Pnl */
            unrealized_pnl?: string | null;
        };
        /** DashboardPositionsData */
        DashboardPositionsData: {
            /** Exchange Count */
            exchange_count: number;
            /**
             * Exchange Status
             * @enum {string}
             */
            exchange_status: "ok" | "stale" | "unconfigured";
            /** Items */
            items: components["schemas"]["DashboardPositionItem"][];
            /** Manual Count */
            manual_count: number;
            /** Total */
            total: number;
        };
        /** DashboardPositionsModule */
        DashboardPositionsModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardPositionsData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /**
         * DashboardRecentBacktest
         * @description 最近 30 天内创建的一次回测；一次回测只代表一个标的，不跨标的求和。
         */
        DashboardRecentBacktest: {
            /** As Of */
            as_of: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Max Drawdown */
            max_drawdown: string;
            /** Run Id */
            run_id: string;
            /** Total Return */
            total_return: string;
            /** Trade Count */
            trade_count: number;
            /** Window Days */
            window_days: number;
        };
        /**
         * DashboardRiskData
         * @description 风险卡：组合级数值与规则命中数量，不重复展开每条持仓的规则明细。
         */
        DashboardRiskData: {
            /** Currency */
            currency: string;
            /** Gross Notional */
            gross_notional: string;
            /** High Leverage Count */
            high_leverage_count: number;
            /** Long Notional */
            long_notional: string;
            /** Margin Usage Basis */
            margin_usage_basis?: ("notional_over_leverage" | "margin_ratio" | "used_margin") | null;
            /** Margin Usage Pct */
            margin_usage_pct?: string | null;
            /** Max Single Instrument Weight Pct */
            max_single_instrument_weight_pct?: string | null;
            /** Missing Stop Count */
            missing_stop_count: number;
            /** Near Stop Count */
            near_stop_count: number;
            /** Net Notional */
            net_notional: string;
            /** Position Count */
            position_count: number;
            /**
             * Risk Level
             * @enum {string}
             */
            risk_level: "low" | "medium" | "high";
            /** Short Notional */
            short_notional: string;
        };
        /** DashboardRiskModule */
        DashboardRiskModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardRiskData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /**
         * DashboardStrategiesData
         * @description 策略卡计数：`total`/`enabled` 来自 v6 `strategies` 表。
         *
         *     v6 策略没有「运行中」状态，`running` 为 `null`，界面按「未提供」显示。
         */
        DashboardStrategiesData: {
            /** Enabled */
            enabled: number;
            /** Pending Signals */
            pending_signals?: number | null;
            recent_backtest?: components["schemas"]["DashboardRecentBacktest"] | null;
            /** Running */
            running?: number | null;
            /** Total */
            total: number;
        };
        /** DashboardStrategiesModule */
        DashboardStrategiesModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardStrategiesData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /**
         * DashboardSummaryResponse
         * @description 首页一次请求返回八个模块；任一模块失败只影响它自己。
         * @example {
         *       "account": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": {
         *           "account_id": "okx-main",
         *           "available_equity": "682.30",
         *           "available_margin": "682.30",
         *           "captured_at": "2026-11-13T09:00:00Z",
         *           "cash_balance": "0",
         *           "currency": "USDT",
         *           "day_pnl_basis": "equity_only",
         *           "equity": "1248.60",
         *           "margin_usage_pct": "45.36",
         *           "source": "okx_rest",
         *           "unrealized_pnl": "31.84",
         *           "used_margin": "566.30"
         *         },
         *         "status": "ok"
         *       },
         *       "activity": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": [],
         *         "status": "ok"
         *       },
         *       "alerts": {
         *         "data": [],
         *         "status": "ok"
         *       },
         *       "as_of": "2026-11-13T09:00:00Z",
         *       "degraded": [],
         *       "market": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": {
         *           "items": [
         *             {
         *               "as_of": "2026-11-13T09:00:00Z",
         *               "bar": "1d",
         *               "breadth": {
         *                 "advancers": 8,
         *                 "decliners": 2,
         *                 "participants": 11,
         *                 "ratio": "4",
         *                 "unchanged": 1
         *               },
         *               "inst_type": "SPOT",
         *               "primary_source": "okx_spot",
         *               "resonance": {
         *                 "participants": 11,
         *                 "strength": "0.62",
         *                 "window": 20
         *               },
         *               "session": "regular"
         *             },
         *             {
         *               "as_of": "2026-11-13T09:00:00Z",
         *               "bar": "1d",
         *               "breadth": {
         *                 "advancers": 5,
         *                 "decliners": 5,
         *                 "participants": 10,
         *                 "ratio": "1",
         *                 "unchanged": 0
         *               },
         *               "inst_type": "SWAP",
         *               "primary_source": "okx_swap",
         *               "resonance": {
         *                 "participants": 10,
         *                 "strength": "0",
         *                 "window": 20
         *               },
         *               "session": "pre"
         *             }
         *           ],
         *           "session": "pre"
         *         },
         *         "status": "ok"
         *       },
         *       "positions": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": {
         *           "exchange_count": 1,
         *           "exchange_status": "ok",
         *           "items": [
         *             {
         *               "display_symbol": "AAPL-USDT",
         *               "inst_id": "AAPL-USDT-SWAP",
         *               "leverage": "3",
         *               "mark_price": "231.42",
         *               "notional": "1851.36",
         *               "position_ref": "exchange:okx-main:123456",
         *               "side": "long",
         *               "source": "exchange",
         *               "unrealized_pnl": "36.96"
         *             }
         *           ],
         *           "manual_count": 0,
         *           "total": 1
         *         },
         *         "status": "ok"
         *       },
         *       "risk": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": {
         *           "currency": "USDT",
         *           "gross_notional": "1851.36",
         *           "high_leverage_count": 0,
         *           "long_notional": "1851.36",
         *           "margin_usage_basis": "margin_ratio",
         *           "margin_usage_pct": "45.36",
         *           "max_single_instrument_weight_pct": "100",
         *           "missing_stop_count": 1,
         *           "near_stop_count": 0,
         *           "net_notional": "1851.36",
         *           "position_count": 1,
         *           "risk_level": "medium",
         *           "short_notional": "0"
         *         },
         *         "status": "ok"
         *       },
         *       "strategies": {
         *         "as_of": "2026-11-13T09:00:00Z",
         *         "data": {
         *           "enabled": 1,
         *           "recent_backtest": {
         *             "as_of": "2026-11-12T10:00:00Z",
         *             "data_source": "okx_swap",
         *             "max_drawdown": "0.061",
         *             "run_id": "bt_0001",
         *             "total_return": "0.124",
         *             "trade_count": 18,
         *             "window_days": 30
         *           },
         *           "total": 2
         *         },
         *         "status": "ok"
         *       },
         *       "watchlist": {
         *         "as_of": "2026-11-12T16:00:00Z",
         *         "data": {
         *           "items": [
         *             {
         *               "change_pct_24h": "1.86",
         *               "data_status": "ok",
         *               "display_symbol": "AAPL",
         *               "inst_id": "XAAPL-USDT",
         *               "last_price": "231.42",
         *               "name": "Apple",
         *               "rsi_14": "61.4",
         *               "trend": "bullish"
         *             }
         *           ],
         *           "summary": {
         *             "bearish": 0,
         *             "bullish": 1,
         *             "coverage_pct": "100",
         *             "total": 1
         *           }
         *         },
         *         "status": "ok"
         *       }
         *     }
         */
        DashboardSummaryResponse: {
            account: components["schemas"]["DashboardAccountModule"];
            activity: components["schemas"]["DashboardActivityModule"];
            alerts: components["schemas"]["DashboardAlertsModule"];
            /** As Of */
            as_of: string;
            /** Degraded */
            degraded: components["schemas"]["DashboardDegradedItem"][];
            market: components["schemas"]["DashboardMarketModule"];
            positions: components["schemas"]["DashboardPositionsModule"];
            risk: components["schemas"]["DashboardRiskModule"];
            strategies: components["schemas"]["DashboardStrategiesModule"];
            watchlist: components["schemas"]["DashboardWatchlistModule"];
        };
        /** DashboardWatchlistData */
        DashboardWatchlistData: {
            /** Items */
            items: components["schemas"]["DashboardWatchlistItem"][];
            summary: components["schemas"]["DashboardWatchlistSummary"];
        };
        /** DashboardWatchlistItem */
        DashboardWatchlistItem: {
            /** Change Pct 24H */
            change_pct_24h?: string | null;
            /**
             * Data Status
             * @enum {string}
             */
            data_status: "ok" | "partial" | "missing";
            /** Display Symbol */
            display_symbol: string;
            /** Inst Id */
            inst_id: string;
            /** Last Price */
            last_price?: string | null;
            /** Name */
            name: string;
            /** Rsi 14 */
            rsi_14?: string | null;
            /** Trend */
            trend?: ("bullish" | "bearish" | "neutral") | null;
        };
        /** DashboardWatchlistModule */
        DashboardWatchlistModule: {
            /** As Of */
            as_of?: string | null;
            data?: components["schemas"]["DashboardWatchlistData"] | null;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unavailable" | "unconfigured";
        };
        /** DashboardWatchlistSummary */
        DashboardWatchlistSummary: {
            /** Bearish */
            bearish: number;
            /** Bullish */
            bullish: number;
            /** Coverage Pct */
            coverage_pct: string;
            /** Total */
            total: number;
        };
        /**
         * DataSourceSettings
         * @description 数据源配置与同步状态；状态字段由服务端读取同步任务表填写。
         */
        DataSourceSettings: {
            equity: components["schemas"]["EquitySettings"];
            /**
             * Failure Count
             * @default 0
             */
            failure_count: number;
            /** Last Sync At */
            last_sync_at?: string | null;
            macro: components["schemas"]["MacroSettings"];
            /** Subscribed Instruments */
            subscribed_instruments?: string[];
        };
        /**
         * DataSourceSettingsUpdate
         * @description 数据源可写字段；最后同步时间与失败次数只读。
         */
        DataSourceSettingsUpdate: {
            equity?: components["schemas"]["EquitySettingsUpdate"] | null;
            macro?: components["schemas"]["MacroSettingsUpdate"] | null;
            /** Subscribed Instruments */
            subscribed_instruments?: string[] | null;
        };
        /**
         * DeliveryItem
         * @description 一行投递台账：哪条告警、走哪个通道、成没成、失败原因与时间。
         */
        DeliveryItem: {
            /** Alert Id */
            alert_id?: string | null;
            /** Channel */
            channel: string;
            /** Created At */
            created_at: string;
            /** Error */
            error?: string | null;
            /** Id */
            id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "delivered" | "failed";
        };
        /**
         * DeliveryListResponse
         * @description 最近若干条投递记录，新的在前；条数由查询上限限制，不做定期清理。
         * @example {
         *       "items": [
         *         {
         *           "alert_id": "al_XAAPL-USDT_20261120120000000000",
         *           "channel": "telegram",
         *           "created_at": "2026-11-20T12:00:03Z",
         *           "id": "nd_3f9c1a7b5e2d4c6f8a0b1c2d",
         *           "status": "delivered"
         *         }
         *       ]
         *     }
         */
        DeliveryListResponse: {
            /** Items */
            items?: components["schemas"]["DeliveryItem"][];
        };
        /**
         * DisplaySettings
         * @description 显示偏好；前端可缓存，后端持久化。
         */
        DisplaySettings: {
            /**
             * Color Scheme
             * @default system
             * @enum {string}
             */
            color_scheme: "system" | "light" | "dark";
            /**
             * Default Bar
             * @default 1d
             * @enum {string}
             */
            default_bar: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /**
             * Home Layout
             * @default cockpit
             */
            home_layout: string;
            /** Homepage Pinned */
            homepage_pinned?: string[];
            /**
             * Price Precision
             * @default 2
             */
            price_precision: number;
        };
        /**
         * DisplaySettingsUpdate
         * @description 显示偏好的可写字段：不提交的字段保持库中原值。
         *
         *     置顶清单的取值规则（形状、长度、重复、是否在自选里）由路由层校验，因此这里
         *     只声明形状、不加约束；`None` 表示本次不改这一项。
         */
        DisplaySettingsUpdate: {
            /** Color Scheme */
            color_scheme?: ("system" | "light" | "dark") | null;
            /** Default Bar */
            default_bar?: ("1m" | "5m" | "15m" | "1h" | "4h" | "1d") | null;
            /** Home Layout */
            home_layout?: string | null;
            /** Homepage Pinned */
            homepage_pinned?: string[] | null;
            /** Price Precision */
            price_precision?: number | null;
        };
        /**
         * EquityCurveResponse
         * @description 一段区间的权益曲线。
         *
         *     `available=false` 表示这段区间还没有足够的数据（快照只有十天时，一个月窗口
         *     只有三分之一），此时 `points` 一定为空，界面显示「这段区间还没有数据」，
         *     **不画线**。`first_snapshot_at` 用于说明「快照自 … 起记录」。
         * @example {
         *       "available": true,
         *       "change_pct": "2.33",
         *       "first_snapshot_at": "2026-11-15T00:00:00Z",
         *       "last_snapshot_at": "2026-11-25T13:51:00Z",
         *       "points": [
         *         {
         *           "at": "2026-11-25T12:51:00Z",
         *           "value": "412.60"
         *         },
         *         {
         *           "at": "2026-11-25T13:51:00Z",
         *           "value": "413.45"
         *         }
         *       ],
         *       "range": "1d"
         *     }
         */
        EquityCurveResponse: {
            /** Available */
            available: boolean;
            /** Change Pct */
            change_pct?: string | null;
            /** First Snapshot At */
            first_snapshot_at?: string | null;
            /** Last Snapshot At */
            last_snapshot_at?: string | null;
            /** Points */
            points: components["schemas"]["CurvePointItem"][];
            /** Range */
            range: string;
        };
        /** EquityPoint */
        EquityPoint: {
            /** Equity */
            equity: string;
            /** Time */
            time: string;
        };
        /**
         * EquitySchedulerSettings
         * @description 美股调度周期：`1m` / `5m`。
         */
        EquitySchedulerSettings: {
            /** Minute */
            minute: string;
        };
        /**
         * EquitySchedulerSettingsUpdate
         * @description 调度周期，只接受实现支持的取值。
         */
        EquitySchedulerSettingsUpdate: {
            /** Minute */
            minute?: ("1m" | "5m") | null;
        };
        /**
         * EquitySettings
         * @description 美股数据源的只读视图；周期由 provider 声明，因此不在这里配置。
         */
        EquitySettings: {
            /** Provider */
            provider: string;
            scheduler: components["schemas"]["EquitySchedulerSettings"];
            /** Symbols */
            symbols?: string[];
        };
        /**
         * EquitySettingsUpdate
         * @description 美股分组的可写字段；未提交的子项保持原值，标的清单整体替换。
         */
        EquitySettingsUpdate: {
            /** Provider */
            provider?: ("yahoo" | "stooq") | null;
            scheduler?: components["schemas"]["EquitySchedulerSettingsUpdate"] | null;
            /** Symbols */
            symbols?: string[] | null;
        };
        /** ExchangePositionItem */
        ExchangePositionItem: {
            /** Asset Class */
            asset_class: string;
            /** Avg Px */
            avg_px: string;
            /** Display Symbol */
            display_symbol: string;
            /** Inst Id */
            inst_id: string;
            /** Lever */
            lever?: string | null;
            /** Liq Px */
            liq_px?: string | null;
            /** Margin */
            margin?: string | null;
            /** Mark Px */
            mark_px?: string | null;
            /** Mgn Mode */
            mgn_mode?: string | null;
            /** Name */
            name: string;
            /** Pos Id */
            pos_id: string;
            /**
             * Pos Side
             * @enum {string}
             */
            pos_side: "long" | "short";
            /** Size */
            size: string;
            /** Upl */
            upl?: string | null;
            /** Upl Ratio */
            upl_ratio?: string | null;
        };
        /**
         * ExchangePositionsResponse
         * @example {
         *       "as_of": "2026-11-13T09:00:00Z",
         *       "items": [
         *         {
         *           "asset_class": "tokenized_equity",
         *           "avg_px": "226.80",
         *           "display_symbol": "AAPL-USDT",
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "lever": "3",
         *           "liq_px": "151.20",
         *           "margin": "604.80",
         *           "mark_px": "231.42",
         *           "mgn_mode": "cross",
         *           "name": "AAPL",
         *           "pos_id": "123456",
         *           "pos_side": "long",
         *           "size": "8",
         *           "upl": "36.96",
         *           "upl_ratio": "0.0204"
         *         }
         *       ],
         *       "status": "ok"
         *     }
         */
        ExchangePositionsResponse: {
            /** As Of */
            as_of?: string | null;
            /** Items */
            items: components["schemas"]["ExchangePositionItem"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unconfigured";
        };
        /**
         * ExchangeSettingsUpdate
         * @description API Key 只写字段；提交后服务端只保存，不读回明文。
         */
        ExchangeSettingsUpdate: {
            /** Api Key */
            api_key?: string | null;
        };
        /**
         * ExecutionSettings
         * @description 自动执行开关：v6 默认关闭，只保存状态，不产生真实订单。
         */
        ExecutionSettings: {
            /**
             * Auto Trading Enabled
             * @default false
             */
            auto_trading_enabled: boolean;
        };
        /** ExposurePositionItem */
        ExposurePositionItem: {
            /** Atr Distance */
            atr_distance?: string | null;
            /** Display Symbol */
            display_symbol: string;
            /** Flags */
            flags: string[];
            /** Inst Id */
            inst_id: string;
            /** Lever */
            lever?: string | null;
            /** Mark Px */
            mark_px?: string | null;
            /** Notional */
            notional?: string | null;
            /** Position Ref */
            position_ref: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /**
             * Source
             * @enum {string}
             */
            source: "exchange" | "manual";
            /** Stop Distance Pct */
            stop_distance_pct?: string | null;
            /** Stop Px */
            stop_px?: string | null;
            /** Stop Status */
            stop_status?: ("confirmed" | "none" | "unavailable") | null;
            /** Weight Pct */
            weight_pct?: string | null;
        };
        /** ExposureRuleItem */
        ExposureRuleItem: {
            /**
             * Level
             * @enum {string}
             */
            level: "warning" | "critical";
            /** Position Ref */
            position_ref?: string | null;
            /** Rule Id */
            rule_id: string;
            /** Threshold */
            threshold?: string | null;
            /** Value */
            value?: string | null;
        };
        /** ExposureSummary */
        ExposureSummary: {
            /** Currency */
            currency: string;
            /** Gross Notional */
            gross_notional: string;
            /** Long Notional */
            long_notional: string;
            /** Margin Usage Basis */
            margin_usage_basis?: ("notional_over_leverage" | "margin_ratio" | "used_margin") | null;
            /** Margin Usage Pct */
            margin_usage_pct?: string | null;
            /** Max Single Instrument Weight Pct */
            max_single_instrument_weight_pct?: string | null;
            /** Net Notional */
            net_notional: string;
            /**
             * Risk Level
             * @enum {string}
             */
            risk_level: "low" | "medium" | "high";
            /** Short Notional */
            short_notional: string;
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
        /**
         * GroupEquityPoint
         * @description 等权组合净值：各成员以首点归一化后取平均，`nav` 从 1 开始。
         */
        GroupEquityPoint: {
            /** Nav */
            nav: string;
            /** Time */
            time: string;
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
         * InstrumentAnalysisResponse
         * @example {
         *       "bar": "1d",
         *       "candles": {
         *         "available_from": "2023-05-01T16:00:00Z",
         *         "available_to": "2026-11-12T16:00:00Z",
         *         "candles": [
         *           {
         *             "close": "231.42",
         *             "data_source": "okx_spot",
         *             "high": "232.10",
         *             "is_closed": true,
         *             "low": "229.44",
         *             "open": "229.80",
         *             "open_time": "2026-11-12T16:00:00Z",
         *             "volume": "1520.335"
         *           }
         *         ],
         *         "data_source": "okx_spot",
         *         "gaps": [],
         *         "overlays": [
         *           {
         *             "name": "MA20",
         *             "points": [
         *               {
         *                 "time": "2026-11-12T16:00:00Z",
         *                 "value": "226.51"
         *               }
         *             ]
         *           },
         *           {
         *             "name": "MA60",
         *             "points": [
         *               {
         *                 "time": "2026-11-12T16:00:00Z",
         *                 "value": "219.08"
         *               }
         *             ]
         *           }
         *         ]
         *       },
         *       "correlations": [
         *         {
         *           "coefficient": "0.68",
         *           "inst_id": "XQQQ-USDT",
         *           "product_key": "QQQ",
         *           "role": "benchmark",
         *           "sample_size": 60,
         *           "window": 60,
         *           "window_end": "2026-11-12T16:00:00Z",
         *           "window_start": "2026-08-20T16:00:00Z"
         *         }
         *       ],
         *       "coverage": [
         *         {
         *           "available": true,
         *           "available_from": "2023-05-01T16:00:00Z",
         *           "available_to": "2026-11-12T16:00:00Z",
         *           "bar": "1d",
         *           "candle_count": 846,
         *           "data_source": "okx_spot",
         *           "gap_count": 0,
         *           "last_synced_at": "2026-11-13T01:00:00Z"
         *         },
         *         {
         *           "available": false,
         *           "bar": "4h",
         *           "candle_count": 0,
         *           "data_source": "okx_spot",
         *           "gap_count": 0,
         *           "unavailable_reason": "尚未同步"
         *         },
         *         {
         *           "available": false,
         *           "bar": "1h",
         *           "candle_count": 0,
         *           "data_source": "okx_spot",
         *           "gap_count": 0,
         *           "unavailable_reason": "尚未同步"
         *         }
         *       ],
         *       "indicators": {
         *         "momentum": {
         *           "macd": "1.28",
         *           "macd_hist": "0.34",
         *           "macd_signal": "0.94",
         *           "rsi14": "61.4"
         *         },
         *         "readings": [
         *           "收盘价 231.42，MA20 为 226.51，价格位于 MA20 上方 2.17%；MA20 的 5 根斜率是 1.42%。",
         *           "RSI(14) 为 61.40，MACD 为 1.2800，信号线为 0.9400，柱状值为 0.3400。",
         *           "当前成交量是 20 根均量的 1.32 倍，近 20 根相对 XQQQ-USDT 的超额收益为 4.60 个百分点。"
         *         ],
         *         "relative_strength": {
         *           "benchmark_inst_id": "XQQQ-USDT",
         *           "benchmark_return_pct": "3.20",
         *           "excess_return_pct": "4.60",
         *           "symbol_return_pct": "7.80",
         *           "window": 20
         *         },
         *         "trend": {
         *           "close": "231.42",
         *           "ma20": "226.51",
         *           "ma20_slope_pct": "1.42",
         *           "ma60": "219.08",
         *           "ma60_slope_pct": "0.86",
         *           "price_vs_ma20_pct": "2.17",
         *           "price_vs_ma60_pct": "5.63",
         *           "slope_window": 5
         *         },
         *         "volatility": {
         *           "atr14": "5.32",
         *           "atr_pct": "2.30",
         *           "atr_pct_avg20": "1.90"
         *         },
         *         "volume": {
         *           "average20": "1151.78",
         *           "current": "1520.335",
         *           "relative": "1.32"
         *         }
         *       },
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
         *       "levels": {
         *         "high20": "238.90",
         *         "high_distance_pct": "3.23",
         *         "low20": "214.10",
         *         "low_distance_pct": "-7.48",
         *         "window": 20
         *       },
         *       "linked_strategies": [
         *         {
         *           "backtest_end_date": "2026-11-01",
         *           "backtest_start_date": "2026-10-01",
         *           "created_at": "2026-11-10T01:20:00Z",
         *           "data_source": "okx_spot",
         *           "max_drawdown_pct": "6.12",
         *           "run_id": "bt_0001",
         *           "strategy_id": "ma_cross",
         *           "strategy_name": "AAPL 趋势",
         *           "strategy_version_id": "sv_0001",
         *           "total_return_pct": "12.4055",
         *           "trade_count": 37
         *         }
         *       ],
         *       "quote": {
         *         "last": {
         *           "as_of": "2026-11-13T16:00:00Z",
         *           "change": "2.84",
         *           "change_pct": "1.24",
         *           "price": "231.42",
         *           "source": "okx_spot"
         *         }
         *       }
         *     }
         */
        InstrumentAnalysisResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1d" | "4h" | "1h";
            candles: components["schemas"]["AnalysisCandles"];
            /** Correlations */
            correlations: components["schemas"]["CorrelationReading"][];
            /** Coverage */
            coverage: components["schemas"]["AnalysisCoverage"][];
            indicators: components["schemas"]["AnalysisIndicators"];
            instrument: components["schemas"]["InstrumentInfo"];
            levels: components["schemas"]["AnalysisLevels"];
            /** Linked Strategies */
            linked_strategies: components["schemas"]["LinkedBacktest"][];
            quote: components["schemas"]["AnalysisQuote"];
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
        /** InstrumentStrategy */
        InstrumentStrategy: {
            /** Category */
            category: string;
            /** Current Version */
            current_version: number;
            /** Current Version Id */
            current_version_id: string;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /** Instrument Ids */
            instrument_ids: string[];
            /** Linked Version Ids */
            linked_version_ids: string[];
            /** Name */
            name: string;
            recent_backtest?: components["schemas"]["StrategyBacktestSummary"] | null;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "validated" | "enabled" | "paused" | "archived";
            /** Strategy Id */
            strategy_id: string;
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Updated At */
            updated_at: string;
        };
        /**
         * InstrumentStrategyListResponse
         * @example {
         *       "items": [
         *         {
         *           "category": "directional",
         *           "current_version": 1,
         *           "current_version_id": "sv_0001",
         *           "direction": "long_only",
         *           "instrument_ids": [
         *             "XAAPL-USDT"
         *           ],
         *           "linked_version_ids": [
         *             "sv_0001"
         *           ],
         *           "name": "AAPL 趋势",
         *           "recent_backtest": {
         *             "backtest_end_date": "2026-11-01",
         *             "backtest_start_date": "2026-10-01",
         *             "created_at": "2026-11-10T01:20:00Z",
         *             "data_source": "okx_spot",
         *             "max_drawdown_pct": "6.12",
         *             "run_id": "bt_0001",
         *             "strategy_version_id": "sv_0001",
         *             "total_return_pct": "12.4055",
         *             "trade_count": 37
         *           },
         *           "status": "draft",
         *           "strategy_id": "st_0001",
         *           "timeframe": "1d",
         *           "updated_at": "2026-11-10T07:00:00Z"
         *         }
         *       ]
         *     }
         */
        InstrumentStrategyListResponse: {
            /** Items */
            items: components["schemas"]["InstrumentStrategy"][];
        };
        /**
         * InstrumentSyncRequest
         * @description 单标的按需同步：周期限定详情页支持的三种，天数留给调用方覆盖默认窗口。
         */
        InstrumentSyncRequest: {
            /**
             * Bar
             * @default 1d
             * @enum {string}
             */
            bar: "1d" | "4h" | "1h";
            /** Days */
            days?: number | null;
        };
        /**
         * InstrumentSyncResponse
         * @description 同步只被接受，不在请求内等待；真正的结果写在 `data_sync_jobs`。
         * @example {
         *       "bar": "1d",
         *       "days": 400,
         *       "inst_id": "XAAPL-USDT",
         *       "requested_at": "2026-11-16T08:00:00Z",
         *       "status": "started"
         *     }
         */
        InstrumentSyncResponse: {
            /**
             * Bar
             * @enum {string}
             */
            bar: "1d" | "4h" | "1h";
            /** Days */
            days: number;
            /** Inst Id */
            inst_id: string;
            /** Requested At */
            requested_at: string;
            /**
             * Status
             * @enum {string}
             */
            status: "started" | "already_running" | "fresh" | "backoff";
        };
        /** LinkedBacktest */
        LinkedBacktest: {
            /**
             * Backtest End Date
             * Format: date
             */
            backtest_end_date: string;
            /**
             * Backtest Start Date
             * Format: date
             */
            backtest_start_date: string;
            /** Created At */
            created_at: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Max Drawdown Pct */
            max_drawdown_pct: string;
            /** Run Id */
            run_id: string;
            /** Strategy Id */
            strategy_id: string;
            /** Strategy Name */
            strategy_name: string;
            /** Strategy Version Id */
            strategy_version_id?: string | null;
            /** Total Return Pct */
            total_return_pct: string;
            /** Trade Count */
            trade_count: number;
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
         * MacroOverviewResponse
         * @description 首页与关注列表要的宏观读数；`stale` 表示上游失败、数值来自上次落库。
         * @example {
         *       "as_of": "2026-11-22T07:01:00Z",
         *       "readings": [
         *         {
         *           "as_of": "2026-11-20T20:59:00Z",
         *           "change": "-0.13",
         *           "granularity": "minute",
         *           "is_delayed": true,
         *           "market_session": "open",
         *           "name": "美国 10 年期国债",
         *           "provider": "yahoo",
         *           "quality_status": "normal",
         *           "series_id": "us10y",
         *           "unit": "%",
         *           "value": "4.92"
         *         },
         *         {
         *           "as_of": "2026-11-20T21:00:00Z",
         *           "change": "-0.12",
         *           "granularity": "daily",
         *           "is_delayed": false,
         *           "market_session": "closed",
         *           "name": "美国 10 年期国债",
         *           "provider": "treasury",
         *           "quality_status": "normal",
         *           "series_id": "us10y",
         *           "unit": "%",
         *           "value": "4.92"
         *         },
         *         {
         *           "as_of": "2026-11-20T21:00:00Z",
         *           "change": "-0.13",
         *           "granularity": "daily",
         *           "is_delayed": false,
         *           "market_session": "closed",
         *           "name": "美国 2 年期国债",
         *           "provider": "treasury",
         *           "quality_status": "normal",
         *           "series_id": "us2y",
         *           "unit": "%",
         *           "value": "4.63"
         *         },
         *         {
         *           "as_of": "2026-11-20T20:59:00Z",
         *           "change": "7.45",
         *           "granularity": "minute",
         *           "is_delayed": true,
         *           "market_session": "open",
         *           "name": "恐慌指数 VIX",
         *           "provider": "yahoo",
         *           "quality_status": "normal",
         *           "regime": "panic",
         *           "series_id": "vix",
         *           "unit": "点",
         *           "value": "35.89"
         *         },
         *         {
         *           "as_of": "2026-11-20T21:00:00Z",
         *           "change": "7.45",
         *           "granularity": "daily",
         *           "is_delayed": false,
         *           "market_session": "closed",
         *           "name": "恐慌指数 VIX",
         *           "provider": "cboe",
         *           "quality_status": "normal",
         *           "regime": "panic",
         *           "series_id": "vix",
         *           "unit": "点",
         *           "value": "35.89"
         *         }
         *       ],
         *       "spread": {
         *         "available": true,
         *         "inverted": false,
         *         "quality_status": "normal",
         *         "sources": [
         *           {
         *             "provider": "treasury"
         *           }
         *         ],
         *         "trading_day": "2026-11-20",
         *         "value_bp": "29"
         *       },
         *       "stale": false
         *     }
         */
        MacroOverviewResponse: {
            /** As Of */
            as_of: string;
            /** Readings */
            readings: components["schemas"]["MacroReading"][];
            spread: components["schemas"]["MacroSpread"];
            /** Stale */
            stale: boolean;
            /** Stale Reason */
            stale_reason: string | null;
        };
        /**
         * MacroReading
         * @description 一个序列在一个粒度上的读数；缺数据时 `value` 为空并给出 `error`。
         */
        MacroReading: {
            /** As Of */
            as_of?: string | null;
            /** Change */
            change?: string | null;
            /** Error */
            error?: string | null;
            /**
             * Granularity
             * @enum {string}
             */
            granularity: "minute" | "daily";
            /**
             * Is Delayed
             * @default false
             */
            is_delayed: boolean;
            /** Market Session */
            market_session?: string | null;
            /** Name */
            name: string;
            /** Provider */
            provider: string;
            /**
             * Quality Status
             * @enum {string}
             */
            quality_status: "normal" | "stale" | "missing";
            /** Regime */
            regime?: ("low" | "normal" | "elevated" | "panic") | null;
            /** Series Id */
            series_id: string;
            /** Source Url */
            source_url?: string | null;
            /** Unit */
            unit: string;
            /** Value */
            value?: string | null;
        };
        /**
         * MacroSchedulerSettings
         * @description 宏观调度周期：`1m` / `5m`。
         */
        MacroSchedulerSettings: {
            /** Minute */
            minute: string;
        };
        /**
         * MacroSchedulerSettingsUpdate
         * @description 调度周期，只接受实现支持的取值。
         */
        MacroSchedulerSettingsUpdate: {
            /** Minute */
            minute?: ("1m" | "5m") | null;
        };
        /**
         * MacroSeriesSettings
         * @description 一个序列两个粒度的当前 provider；没有配置的粒度给 `null`。
         */
        MacroSeriesSettings: {
            /** Daily */
            daily?: string | null;
            /** Minute */
            minute?: string | null;
        };
        /**
         * MacroSeriesSettingsUpdate
         * @description 按粒度切换 provider；只提交改动的那一项。
         */
        MacroSeriesSettingsUpdate: {
            /** Daily */
            daily?: ("treasury" | "cboe" | "yahoo") | null;
            /** Minute */
            minute?: ("treasury" | "cboe" | "yahoo") | null;
        };
        /**
         * MacroSettings
         * @description 宏观数据源配置的只读视图；上游地址属于服务端内部参数，不经 HTTP 暴露。
         */
        MacroSettings: {
            scheduler: components["schemas"]["MacroSchedulerSettings"];
            /** Series */
            series: {
                [key: string]: components["schemas"]["MacroSeriesSettings"];
            };
        };
        /**
         * MacroSettingsUpdate
         * @description 宏观分组的可写字段；未提交的序列与子项保持原值。
         */
        MacroSettingsUpdate: {
            scheduler?: components["schemas"]["MacroSchedulerSettingsUpdate"] | null;
            /** Series */
            series?: {
                [key: string]: components["schemas"]["MacroSeriesSettingsUpdate"];
            } | null;
        };
        /**
         * MacroSource
         * @description 一个来源：provider 名与它的上游地址。
         */
        MacroSource: {
            /** Provider */
            provider: string;
            /** Source Url */
            source_url?: string | null;
        };
        /**
         * MacroSpread
         * @description 2Y→10Y 利差；`available=false` 时 `reason` 说明为什么算不出来。
         *
         *     `sources` 是配对实际用到的日线来源：默认配置下 2Y 与 10Y 都来自财政部，合成一条；
         *     两个序列配成不同 provider 时给出两条，不把两个来源写成一个。
         */
        MacroSpread: {
            /** Available */
            available: boolean;
            /**
             * Inverted
             * @default false
             */
            inverted: boolean;
            /**
             * Quality Status
             * @enum {string}
             */
            quality_status: "normal" | "stale" | "missing";
            /** Reason */
            reason?: string | null;
            /** Sources */
            sources: components["schemas"]["MacroSource"][];
            /** Trading Day */
            trading_day?: string | null;
            /** Value Bp */
            value_bp?: string | null;
        };
        /**
         * MacroSyncResponse
         * @description 一次手动刷新的结果，按单元逐条返回。
         * @example {
         *       "as_of": "2026-11-22T07:01:00Z",
         *       "results": [
         *         {
         *           "granularity": "minute",
         *           "provider": "yahoo",
         *           "rows": 400,
         *           "series_id": "us10y",
         *           "status": "synced"
         *         },
         *         {
         *           "granularity": "minute",
         *           "provider": "yahoo",
         *           "rows": 0,
         *           "series_id": "vix",
         *           "status": "skipped"
         *         }
         *       ]
         *     }
         */
        MacroSyncResponse: {
            /** As Of */
            as_of: string;
            /** Results */
            results: components["schemas"]["MacroSyncResultItem"][];
        };
        /**
         * MacroSyncResultItem
         * @description 一个抓取单元的手动刷新结果；`skipped` 表示同一单元正在跑。
         */
        MacroSyncResultItem: {
            /** Error */
            error?: string | null;
            /**
             * Granularity
             * @enum {string}
             */
            granularity: "minute" | "daily";
            /** Provider */
            provider: string;
            /** Rows */
            rows: number;
            /** Series Id */
            series_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "synced" | "unchanged" | "skipped" | "failed";
        };
        /**
         * ManualPositionCreateRequest
         * @description 创建手动持仓；`idempotency_key` 由客户端提供，重复提交不重复入账。
         */
        ManualPositionCreateRequest: {
            /** Avg Cost */
            avg_cost: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Inst Id */
            inst_id: string;
            /** Leverage */
            leverage?: string | null;
            /** Note */
            note?: string | null;
            /** Quantity */
            quantity: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /** Stop Px */
            stop_px?: string | null;
        };
        /**
         * ManualPositionItem
         * @example {
         *       "asset_class": "tokenized_equity",
         *       "avg_cost": "226.80",
         *       "created_at": "2026-11-13T09:00:00Z",
         *       "display_symbol": "AAPL-USDT",
         *       "id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
         *       "inst_id": "AAPL-USDT-SWAP",
         *       "leverage": "3",
         *       "market_value": "1851.36",
         *       "name": "AAPL",
         *       "note": "手动记账",
         *       "price": "231.42",
         *       "price_source": "okx_swap",
         *       "price_status": "ok",
         *       "quantity": "8",
         *       "side": "long",
         *       "status": "open",
         *       "stop_px": "200.00",
         *       "unrealized_pnl": "36.96",
         *       "updated_at": "2026-11-13T09:00:00Z"
         *     }
         */
        ManualPositionItem: {
            /** Asset Class */
            asset_class: string;
            /** Avg Cost */
            avg_cost: string;
            /** Created At */
            created_at: string;
            /** Display Symbol */
            display_symbol: string;
            /** Id */
            id: string;
            /** Inst Id */
            inst_id: string;
            /** Leverage */
            leverage?: string | null;
            /** Market Value */
            market_value?: string | null;
            /** Name */
            name: string;
            /** Note */
            note?: string | null;
            /** Price */
            price?: string | null;
            /** Price Source */
            price_source?: ("okx" | "okx_spot" | "okx_swap") | null;
            /**
             * Price Status
             * @enum {string}
             */
            price_status: "ok" | "unavailable";
            /** Quantity */
            quantity: string;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /**
             * Status
             * @enum {string}
             */
            status: "open" | "closed";
            /** Stop Px */
            stop_px?: string | null;
            /** Unrealized Pnl */
            unrealized_pnl?: string | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * ManualPositionListResponse
         * @example {
         *       "items": [
         *         {
         *           "asset_class": "tokenized_equity",
         *           "avg_cost": "226.80",
         *           "created_at": "2026-11-13T09:00:00Z",
         *           "display_symbol": "AAPL-USDT",
         *           "id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "leverage": "3",
         *           "market_value": "1851.36",
         *           "name": "AAPL",
         *           "note": "手动记账",
         *           "price": "231.42",
         *           "price_source": "okx_swap",
         *           "price_status": "ok",
         *           "quantity": "8",
         *           "side": "long",
         *           "status": "open",
         *           "stop_px": "200.00",
         *           "unrealized_pnl": "36.96",
         *           "updated_at": "2026-11-13T09:00:00Z"
         *         }
         *       ]
         *     }
         */
        ManualPositionListResponse: {
            /** Items */
            items: components["schemas"]["ManualPositionItem"][];
        };
        /**
         * ManualPositionUpdateRequest
         * @description 只允许改止损价、杠杆与备注；数量和成本只能通过流水改变。
         */
        ManualPositionUpdateRequest: {
            /** Leverage */
            leverage?: string | null;
            /** Note */
            note?: string | null;
            /** Stop Px */
            stop_px?: string | null;
        };
        /**
         * ManualTradeItem
         * @example {
         *       "action": "reduce",
         *       "created_at": "2026-11-13T10:00:00Z",
         *       "fee": "0.10",
         *       "id": "e2a3d4c5-b6f7-4a89-8b0c-1d2e3f4a5b6c",
         *       "note": "部分卖出",
         *       "occurred_at": "2026-11-13T10:00:00Z",
         *       "position_avg_cost_after": "226.80",
         *       "position_id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
         *       "position_quantity_after": "5",
         *       "position_status_after": "open",
         *       "price": "240.00",
         *       "quantity": "3",
         *       "realized_pnl": "39.50"
         *     }
         */
        ManualTradeItem: {
            /**
             * Action
             * @enum {string}
             */
            action: "open" | "add" | "reduce" | "close" | "correct";
            /** Created At */
            created_at: string;
            /** Fee */
            fee: string;
            /** Id */
            id: string;
            /** Note */
            note?: string | null;
            /** Occurred At */
            occurred_at: string;
            /** Position Avg Cost After */
            position_avg_cost_after: string;
            /** Position Id */
            position_id: string;
            /** Position Quantity After */
            position_quantity_after: string;
            /**
             * Position Status After
             * @enum {string}
             */
            position_status_after: "open" | "closed";
            /** Price */
            price: string;
            /** Quantity */
            quantity: string;
            /** Realized Pnl */
            realized_pnl?: string | null;
        };
        /**
         * ManualTradeListResponse
         * @example {
         *       "items": [
         *         {
         *           "action": "reduce",
         *           "created_at": "2026-11-13T10:00:00Z",
         *           "fee": "0.10",
         *           "id": "e2a3d4c5-b6f7-4a89-8b0c-1d2e3f4a5b6c",
         *           "note": "部分卖出",
         *           "occurred_at": "2026-11-13T10:00:00Z",
         *           "position_avg_cost_after": "226.80",
         *           "position_id": "0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
         *           "position_quantity_after": "5",
         *           "position_status_after": "open",
         *           "price": "240.00",
         *           "quantity": "3",
         *           "realized_pnl": "39.50"
         *         }
         *       ]
         *     }
         */
        ManualTradeListResponse: {
            /** Items */
            items: components["schemas"]["ManualTradeItem"][];
        };
        /** ManualTradeRequest */
        ManualTradeRequest: {
            /**
             * Action
             * @enum {string}
             */
            action: "add" | "reduce" | "close" | "correct";
            /**
             * Fee
             * @default 0
             */
            fee: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Note */
            note?: string | null;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Price */
            price: string;
            /** Quantity */
            quantity: string;
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
         * MarketBreadthResponse
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
        MarketBreadthResponse: {
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
         * MarketOverviewItem
         * @description 一个市场指标；缺数据时数值为 `null`，`quality_status` 说明原因。
         */
        MarketOverviewItem: {
            /** As Of */
            as_of: string | null;
            /** Change */
            change: string | null;
            /** Change Pct */
            change_pct: string | null;
            /** Is Delayed */
            is_delayed: boolean;
            /** Market Session */
            market_session: string;
            /** Name */
            name: string;
            /**
             * Quality Status
             * @enum {string}
             */
            quality_status: "normal" | "missing" | "delayed" | "stale" | "abnormal" | "pending";
            /** Source */
            source: string;
            /** Source Url */
            source_url?: string | null;
            /** Symbol */
            symbol: string;
            /** Value */
            value: string | null;
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
         * MarketSnapshotResponse
         * @description BTC 的当前快照；顶层 `stale` 表示这项数据不能当作实时值。
         * @example {
         *       "as_of": "2026-11-15T06:10:00Z",
         *       "items": [
         *         {
         *           "as_of": "2026-11-15T06:09:30Z",
         *           "change": "1200",
         *           "change_pct": "1.88",
         *           "is_delayed": false,
         *           "market_session": "regular",
         *           "name": "Bitcoin",
         *           "quality_status": "normal",
         *           "source": "okx_spot",
         *           "symbol": "BTC",
         *           "value": "65000.5"
         *         }
         *       ],
         *       "stale": false
         *     }
         */
        MarketSnapshotResponse: {
            /** As Of */
            as_of: string;
            /** Items */
            items: components["schemas"]["MarketOverviewItem"][];
            /** Stale */
            stale: boolean;
            /** Stale Reason */
            stale_reason: string | null;
        };
        /**
         * MergedPositionItem
         * @description `GET /api/positions` 的一行：两种来源统一字段，来源专属字段可为空。
         */
        MergedPositionItem: {
            /** Asset Class */
            asset_class: string;
            /** Avg Px */
            avg_px: string;
            /** Display Symbol */
            display_symbol: string;
            /** Inst Id */
            inst_id: string;
            /** Lever */
            lever?: string | null;
            /** Liq Px */
            liq_px?: string | null;
            /** Margin */
            margin?: string | null;
            /** Mark Px */
            mark_px?: string | null;
            /** Mgn Mode */
            mgn_mode?: string | null;
            /** Name */
            name: string;
            /** Notional */
            notional?: string | null;
            /** Position Ref */
            position_ref: string;
            /** Price Status */
            price_status?: ("ok" | "unavailable") | null;
            /**
             * Side
             * @enum {string}
             */
            side: "long" | "short";
            /** Size */
            size: string;
            /**
             * Source
             * @enum {string}
             */
            source: "exchange" | "manual";
            /** Stop Distance Pct */
            stop_distance_pct?: string | null;
            /** Stop Px */
            stop_px?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /** Upl */
            upl?: string | null;
            /** Upl Ratio */
            upl_ratio?: string | null;
        };
        /**
         * MergedPositionsResponse
         * @description OKX 与手动持仓的合并视图；`exchange_status` 只说明交易所同步状态。
         * @example {
         *       "as_of": "2026-11-13T09:00:00Z",
         *       "exchange_status": "ok",
         *       "items": [
         *         {
         *           "asset_class": "tokenized_equity",
         *           "avg_px": "226.80",
         *           "display_symbol": "AAPL-USDT",
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "lever": "3",
         *           "liq_px": "151.20",
         *           "margin": "604.80",
         *           "mark_px": "231.42",
         *           "mgn_mode": "cross",
         *           "name": "AAPL",
         *           "notional": "1851.36",
         *           "position_ref": "exchange:okx-main:123456",
         *           "side": "long",
         *           "size": "8",
         *           "source": "exchange",
         *           "updated_at": "2026-11-13T09:00:00Z",
         *           "upl": "36.96",
         *           "upl_ratio": "0.0204"
         *         },
         *         {
         *           "asset_class": "tokenized_equity",
         *           "avg_px": "55",
         *           "display_symbol": "AAPL-USDT",
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "lever": "2",
         *           "mark_px": "60.5",
         *           "name": "AAPL",
         *           "notional": "121",
         *           "position_ref": "manual:0f6f6f0e-5b6f-4f0c-9b7a-7e5f8a1d2c34",
         *           "price_status": "ok",
         *           "side": "long",
         *           "size": "2",
         *           "source": "manual",
         *           "stop_distance_pct": "4.132231404959",
         *           "stop_px": "58",
         *           "updated_at": "2026-11-13T09:00:00Z",
         *           "upl": "11"
         *         }
         *       ]
         *     }
         */
        MergedPositionsResponse: {
            /** As Of */
            as_of?: string | null;
            /**
             * Exchange Status
             * @enum {string}
             */
            exchange_status: "ok" | "stale" | "unconfigured";
            /** Items */
            items: components["schemas"]["MergedPositionItem"][];
        };
        /** MomentumIndicators */
        MomentumIndicators: {
            /** Macd */
            macd?: string | null;
            /** Macd Hist */
            macd_hist?: string | null;
            /** Macd Signal */
            macd_signal?: string | null;
            /** Rsi14 */
            rsi14?: string | null;
        };
        /**
         * NotificationChannelTestRequest
         * @description 测试发送：只针对两个外部通道，浏览器通道不需要（页面自己就能验证）。
         */
        NotificationChannelTestRequest: {
            /**
             * Channel
             * @enum {string}
             */
            channel: "telegram" | "webhook";
        };
        /**
         * NotificationChannelTestResponse
         * @description 测试发送的结果：与投递台账同一套状态与失败原因。
         * @example {
         *       "channel": "telegram",
         *       "status": "delivered"
         *     }
         */
        NotificationChannelTestResponse: {
            /** Channel */
            channel: string;
            /** Error */
            error?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "delivered" | "failed";
        };
        /**
         * NotificationSettings
         * @description 通知通道开关、两个可编辑的接收方，以及按通道的类型订阅。
         */
        NotificationSettings: {
            /** Channels */
            channels?: string[];
            subscriptions?: components["schemas"]["NotificationSubscriptions"];
            telegram?: components["schemas"]["TelegramSettings"];
            webhook?: components["schemas"]["WebhookSettings"];
        };
        /**
         * NotificationSettingsUpdate
         * @description 按子项改通知设置：不提交的子项保持原值，空通道清单表示一个通道都不开。
         */
        NotificationSettingsUpdate: {
            /** Channels */
            channels?: string[] | null;
            subscriptions?: components["schemas"]["NotificationSubscriptionsUpdate"] | null;
            telegram?: components["schemas"]["TelegramSettingsUpdate"] | null;
            webhook?: components["schemas"]["WebhookSettingsUpdate"] | null;
        };
        /**
         * NotificationSubscriptions
         * @description 三个通道各自的订阅；读取时缺项按默认值补齐。
         */
        NotificationSubscriptions: {
            browser?: components["schemas"]["ChannelSubscriptionSettings"];
            telegram?: components["schemas"]["ChannelSubscriptionSettings"];
            webhook?: components["schemas"]["ChannelSubscriptionSettings"];
        };
        /**
         * NotificationSubscriptionsUpdate
         * @description 按通道、按字段部分更新订阅：只提交要改的通道与字段，其余保持原值。
         */
        NotificationSubscriptionsUpdate: {
            browser?: components["schemas"]["ChannelSubscriptionUpdate"] | null;
            telegram?: components["schemas"]["ChannelSubscriptionUpdate"] | null;
            webhook?: components["schemas"]["ChannelSubscriptionUpdate"] | null;
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
         * OrderHistoryItem
         * @description 单标的一笔订单；`is_open` 区分挂单与历史，`pnl` / `fee` 缺失时为 `null`。
         */
        OrderHistoryItem: {
            /** Avg Px */
            avg_px?: string | null;
            /** Fee */
            fee?: string | null;
            /** Filled Qty */
            filled_qty: string;
            /** Is Open */
            is_open: boolean;
            /** Order Id */
            order_id: string;
            /** Order Type */
            order_type: string;
            /** Pnl */
            pnl?: string | null;
            /** Price */
            price?: string | null;
            /** Qty */
            qty: string;
            /**
             * Side
             * @enum {string}
             */
            side: "buy" | "sell";
            /** Status */
            status: string;
            /** Ts */
            ts: string;
        };
        /**
         * OrderHistoryResponse
         * @description 单标的订单历史；近 7 天来自 `orders-history`，更早来自归档（最多 3 个月）。
         * @example {
         *       "inst_id": "BTC-USDT-SWAP",
         *       "items": [
         *         {
         *           "avg_px": "60520",
         *           "fee": "-0.03",
         *           "filled_qty": "0.2",
         *           "is_open": false,
         *           "order_id": "3123456789",
         *           "order_type": "limit",
         *           "pnl": "1.84",
         *           "price": "60520",
         *           "qty": "0.2",
         *           "side": "sell",
         *           "status": "filled",
         *           "ts": "2026-11-25T09:09:00Z"
         *         }
         *       ],
         *       "scope": "all",
         *       "window_days": 90
         *     }
         */
        OrderHistoryResponse: {
            /** Inst Id */
            inst_id: string;
            /** Items */
            items: components["schemas"]["OrderHistoryItem"][];
            /**
             * Scope
             * @enum {string}
             */
            scope: "all" | "open" | "history";
            /** Window Days */
            window_days: number;
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
            /** Unrealized Pnl */
            unrealized_pnl: string;
        };
        /**
         * PositionCardItem
         * @description 一张持仓卡片需要的全部事实，盈亏、占比与止损距离都由后端算好。
         */
        PositionCardItem: {
            /** Asset Class */
            asset_class: string;
            /** Avg Px */
            avg_px: string;
            /** Display Symbol */
            display_symbol: string;
            /** Inst Id */
            inst_id: string;
            /** Inst Type */
            inst_type?: ("SPOT" | "SWAP") | null;
            /** Lever */
            lever?: string | null;
            /** Liq Px */
            liq_px?: string | null;
            /** Margin */
            margin?: string | null;
            /** Mark Px */
            mark_px?: string | null;
            /** Mark Px Age Days */
            mark_px_age_days?: number | null;
            /** Mark Px At */
            mark_px_at?: string | null;
            /** Mark Px Source */
            mark_px_source?: string | null;
            /**
             * Mark Px Stale
             * @default false
             */
            mark_px_stale: boolean;
            /** Mgn Mode */
            mgn_mode?: string | null;
            /** Name */
            name: string;
            /** Notional */
            notional?: string | null;
            /** Pos Id */
            pos_id: string;
            /**
             * Pos Side
             * @enum {string}
             */
            pos_side: "long" | "short";
            /** Size */
            size: string;
            /** Stop Distance Pct */
            stop_distance_pct?: string | null;
            /** Stop Px */
            stop_px?: string | null;
            /**
             * Stop Status
             * @enum {string}
             */
            stop_status: "confirmed" | "none" | "unavailable";
            /** Stop Supported */
            stop_supported: boolean;
            /** Upl */
            upl?: string | null;
            /** Upl Curve */
            upl_curve: components["schemas"]["CurvePointItem"][];
            /** Upl Ratio */
            upl_ratio?: string | null;
            /** Weight Pct */
            weight_pct?: string | null;
        };
        /**
         * PositionCardsResponse
         * @description 持仓卡片列表，已按未实现盈亏绝对值降序。
         *
         *     `hidden_dust_count` 是展示层隐藏的尘埃条数；快照里一行都没删，`items` 合计的
         *     `weight_pct` 因此仍是 100%。
         * @example {
         *       "as_of": "2026-11-25T13:51:00Z",
         *       "hidden_dust_count": 0,
         *       "items": [
         *         {
         *           "asset_class": "equity_perp",
         *           "avg_px": "269.34",
         *           "display_symbol": "GOOGL-USDT",
         *           "inst_id": "GOOGL-USDT-SWAP",
         *           "inst_type": "SWAP",
         *           "lever": "10",
         *           "margin": "57.83",
         *           "mark_px": "276.71",
         *           "mark_px_at": "2026-11-25T13:51:00Z",
         *           "mark_px_source": "okx_rest",
         *           "mark_px_stale": false,
         *           "mgn_mode": "isolated",
         *           "name": "Alphabet",
         *           "notional": "578.32",
         *           "pos_id": "GOOGL-USDT-SWAP:long",
         *           "pos_side": "long",
         *           "size": "2.09",
         *           "stop_status": "none",
         *           "stop_supported": true,
         *           "upl": "15.40",
         *           "upl_curve": [
         *             {
         *               "at": "2026-11-25T12:51:00Z",
         *               "value": "12.10"
         *             },
         *             {
         *               "at": "2026-11-25T13:51:00Z",
         *               "value": "15.40"
         *             }
         *           ],
         *           "upl_ratio": "0.0274",
         *           "weight_pct": "79.12"
         *         }
         *       ],
         *       "status": "ok"
         *     }
         */
        PositionCardsResponse: {
            /** As Of */
            as_of?: string | null;
            /**
             * Hidden Dust Count
             * @default 0
             */
            hidden_dust_count: number;
            /** Items */
            items: components["schemas"]["PositionCardItem"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "unconfigured";
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
         * PositionRiskConfigResponse
         * @example {
         *       "position_ref": "exchange:okx-main:123456",
         *       "risk_budget": "50",
         *       "source": "local",
         *       "stop_px": "210.00",
         *       "updated_at": "2026-11-13T09:00:00Z",
         *       "warning_threshold_pct": "1.5"
         *     }
         */
        PositionRiskConfigResponse: {
            /** Position Ref */
            position_ref: string;
            /** Risk Budget */
            risk_budget?: string | null;
            /** Source */
            source: string;
            /** Stop Px */
            stop_px?: string | null;
            /** Updated At */
            updated_at: string;
            /** Warning Threshold Pct */
            warning_threshold_pct?: string | null;
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
        /** RelativeStrengthIndicators */
        RelativeStrengthIndicators: {
            /** Benchmark Inst Id */
            benchmark_inst_id?: string | null;
            /** Benchmark Return Pct */
            benchmark_return_pct?: string | null;
            /** Excess Return Pct */
            excess_return_pct?: string | null;
            /** Symbol Return Pct */
            symbol_return_pct?: string | null;
            /** Window */
            window: number;
        };
        /** ResearchNoteCreateRequest */
        ResearchNoteCreateRequest: {
            /** Content */
            content: string;
            /** Related Backtest Id */
            related_backtest_id?: string | null;
            /** Related Instrument Id */
            related_instrument_id?: string | null;
            /** Related Strategy Id */
            related_strategy_id?: string | null;
            /** Tags */
            tags?: string[];
            /** Title */
            title: string;
            /**
             * Type
             * @enum {string}
             */
            type: "hypothesis" | "backtest_conclusion" | "decision" | "review";
        };
        /**
         * ResearchNoteCreatedResponse
         * @example {
         *       "created_at": "2026-11-10T23:00:00Z",
         *       "id": "rn_0001",
         *       "title": "AAPL 突破假设",
         *       "type": "hypothesis"
         *     }
         */
        ResearchNoteCreatedResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Title */
            title: string;
            /**
             * Type
             * @enum {string}
             */
            type: "hypothesis" | "backtest_conclusion" | "decision" | "review";
        };
        /**
         * ResearchNoteItem
         * @example {
         *       "content": "收盘价站上 MA20 后观察三日",
         *       "created_at": "2026-11-10T23:00:00Z",
         *       "id": "rn_0001",
         *       "related_backtest_id": "bt_0001",
         *       "related_instrument_id": "XAAPL-USDT",
         *       "related_strategy_id": "st_0001",
         *       "tags": [
         *         "趋势",
         *         "验证中"
         *       ],
         *       "title": "AAPL 突破假设",
         *       "type": "hypothesis",
         *       "updated_at": "2026-11-10T23:00:00Z"
         *     }
         */
        ResearchNoteItem: {
            /** Content */
            content: string;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Related Backtest Id */
            related_backtest_id?: string | null;
            /** Related Instrument Id */
            related_instrument_id?: string | null;
            /** Related Strategy Id */
            related_strategy_id?: string | null;
            /** Tags */
            tags: string[];
            /** Title */
            title: string;
            /**
             * Type
             * @enum {string}
             */
            type: "hypothesis" | "backtest_conclusion" | "decision" | "review";
            /** Updated At */
            updated_at: string;
        };
        /**
         * ResearchNoteListResponse
         * @example {
         *       "items": [
         *         {
         *           "content": "收盘价站上 MA20 后观察三日",
         *           "created_at": "2026-11-10T23:00:00Z",
         *           "id": "rn_0001",
         *           "related_backtest_id": "bt_0001",
         *           "related_instrument_id": "XAAPL-USDT",
         *           "related_strategy_id": "st_0001",
         *           "tags": [
         *             "趋势",
         *             "验证中"
         *           ],
         *           "title": "AAPL 突破假设",
         *           "type": "hypothesis",
         *           "updated_at": "2026-11-10T23:00:00Z"
         *         }
         *       ]
         *     }
         */
        ResearchNoteListResponse: {
            /** Items */
            items: components["schemas"]["ResearchNoteItem"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /** ResearchNoteUpdateRequest */
        ResearchNoteUpdateRequest: {
            /** Content */
            content?: string | null;
            /** Related Backtest Id */
            related_backtest_id?: string | null;
            /** Related Instrument Id */
            related_instrument_id?: string | null;
            /** Related Strategy Id */
            related_strategy_id?: string | null;
            /** Tags */
            tags?: string[] | null;
            /** Title */
            title?: string | null;
            /** Type */
            type?: ("hypothesis" | "backtest_conclusion" | "decision" | "review") | null;
        };
        /**
         * ResearchNoteUpdatedResponse
         * @example {
         *       "created_at": "2026-11-10T23:00:00Z",
         *       "id": "rn_0001",
         *       "title": "AAPL 突破假设（更新）",
         *       "type": "hypothesis",
         *       "updated_at": "2026-11-11T01:00:00Z"
         *     }
         */
        ResearchNoteUpdatedResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Title */
            title: string;
            /**
             * Type
             * @enum {string}
             */
            type: "hypothesis" | "backtest_conclusion" | "decision" | "review";
            /** Updated At */
            updated_at: string;
        };
        /**
         * RiskConfigUpdateRequest
         * @description 本地风险配置的部分更新；显式传 `null` 表示清除该字段。
         */
        RiskConfigUpdateRequest: {
            /** Risk Budget */
            risk_budget?: string | null;
            /** Stop Px */
            stop_px?: string | null;
            /** Warning Threshold Pct */
            warning_threshold_pct?: string | null;
        };
        /**
         * RiskDefaults
         * @description 策略默认风险参数；不是执行风控限额。
         */
        RiskDefaults: {
            /**
             * Default Leverage
             * @default 3
             */
            default_leverage: string;
            /**
             * Risk Budget Per Trade
             * @default 100
             */
            risk_budget_per_trade: string;
            /**
             * Stop Rule
             * @default fixed_pct
             */
            stop_rule: string;
            /**
             * Warning Threshold
             * @default 80
             */
            warning_threshold: string;
        };
        /**
         * RiskEvent
         * @example {
         *       "action": "warn",
         *       "created_at": "2026-11-13T02:00:00Z",
         *       "detail": "单笔金额 3000 超过组合权益的 0.20, 上限 2000",
         *       "event_id": "re_3f2a9c1d",
         *       "inst_id": "XAAPL-USDT",
         *       "instance_id": "si_0001",
         *       "rule": "order_amount_ratio",
         *       "severity": "light",
         *       "target_product_key": "AAPL"
         *     }
         */
        RiskEvent: {
            /** Action */
            action?: string | null;
            /** Created At */
            created_at: string;
            /** Detail */
            detail: string;
            /** Event Id */
            event_id: string;
            /** Inst Id */
            inst_id?: string | null;
            /** Instance Id */
            instance_id?: string | null;
            /** Overridden Approval Id */
            overridden_approval_id?: string | null;
            /** Resolved At */
            resolved_at?: string | null;
            /** Rule */
            rule: string;
            /** Severity */
            severity?: string | null;
            /** Target Product Key */
            target_product_key?: string | null;
        };
        /**
         * RiskEventListResponse
         * @example {
         *       "items": [
         *         {
         *           "action": "warn",
         *           "created_at": "2026-11-13T02:00:00Z",
         *           "detail": "单笔金额 3000 超过组合权益的 0.20, 上限 2000",
         *           "event_id": "re_3f2a9c1d",
         *           "inst_id": "XAAPL-USDT",
         *           "instance_id": "si_0001",
         *           "rule": "order_amount_ratio",
         *           "severity": "light",
         *           "target_product_key": "AAPL"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        RiskEventListResponse: {
            /** Items */
            items: components["schemas"]["RiskEvent"][];
            /** Total */
            total: number;
        };
        /**
         * RiskExposureResponse
         * @example {
         *       "as_of": "2026-11-13T09:00:00Z",
         *       "positions": [
         *         {
         *           "atr_distance": "3.8",
         *           "display_symbol": "AAPL-USDT",
         *           "flags": [],
         *           "inst_id": "AAPL-USDT-SWAP",
         *           "lever": "3",
         *           "mark_px": "231.42",
         *           "notional": "1851.36",
         *           "position_ref": "exchange:okx-main:123456",
         *           "side": "long",
         *           "source": "exchange",
         *           "stop_distance_pct": "9.25",
         *           "stop_px": "210.00",
         *           "stop_status": "confirmed",
         *           "weight_pct": "42.14"
         *         }
         *       ],
         *       "rules": [
         *         {
         *           "level": "warning",
         *           "position_ref": "exchange:okx-main:123456",
         *           "rule_id": "stop_distance",
         *           "threshold": "1",
         *           "value": "0.8"
         *         }
         *       ],
         *       "sectors": [
         *         {
         *           "notional": "1200.00",
         *           "sector": "semiconductor",
         *           "weight_pct": "27.32"
         *         }
         *       ],
         *       "status": "ok",
         *       "summary": {
         *         "currency": "USDT",
         *         "gross_notional": "4393.20",
         *         "long_notional": "3412.80",
         *         "margin_usage_basis": "notional_over_leverage",
         *         "margin_usage_pct": "45.36",
         *         "max_single_instrument_weight_pct": "42.14",
         *         "net_notional": "2432.40",
         *         "risk_level": "low",
         *         "short_notional": "980.40"
         *       }
         *     }
         */
        RiskExposureResponse: {
            /** As Of */
            as_of: string;
            /** Positions */
            positions: components["schemas"]["ExposurePositionItem"][];
            /** Rules */
            rules: components["schemas"]["ExposureRuleItem"][];
            /** Sectors */
            sectors: components["schemas"]["SectorExposureItem"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "empty";
            summary: components["schemas"]["ExposureSummary"];
        };
        /**
         * RiskNotifyConfigResponse
         * @description 五条风控通知规则的完整配置，顺序固定。
         * @example {
         *       "rules": [
         *         {
         *           "channels": [
         *             "browser"
         *           ],
         *           "enabled": true,
         *           "rule_id": "stop_missing"
         *         },
         *         {
         *           "channels": [
         *             "browser",
         *             "telegram"
         *           ],
         *           "enabled": true,
         *           "rule_id": "high_leverage",
         *           "threshold": "5"
         *         }
         *       ]
         *     }
         */
        RiskNotifyConfigResponse: {
            /** Rules */
            rules: components["schemas"]["RiskNotifyRuleItem"][];
        };
        /**
         * RiskNotifyConfigUpdateRequest
         * @description 批量更新通知规则；只提交的规则会被改动。
         */
        RiskNotifyConfigUpdateRequest: {
            /** Rules */
            rules: components["schemas"]["RiskNotifyRuleUpdate"][];
        };
        /**
         * RiskNotifyRuleItem
         * @description 一条风控通知规则：开关、渠道与阈值。
         *
         *     阈值为 `null` 的规则（未挂止损）没有可调数字；其余规则的阈值就是敞口计算用的
         *     那一份，不另存副本。
         */
        RiskNotifyRuleItem: {
            /** Channels */
            channels: ("browser" | "telegram" | "webhook")[];
            /** Enabled */
            enabled: boolean;
            /** Rule Id */
            rule_id: string;
            /** Threshold */
            threshold?: string | null;
        };
        /**
         * RiskNotifyRuleUpdate
         * @description 单条规则的部分更新；未提交的字段保持原值。
         */
        RiskNotifyRuleUpdate: {
            /** Channels */
            channels?: ("browser" | "telegram" | "webhook")[] | null;
            /** Enabled */
            enabled?: boolean | null;
            /** Rule Id */
            rule_id: string;
            /** Threshold */
            threshold?: string | null;
        };
        /**
         * SecretSettings
         * @description 密钥状态：只读，永不返回明文。
         */
        SecretSettings: {
            /** Okx Api Key Masked */
            okx_api_key_masked?: string | null;
            /** Okx Configured */
            okx_configured: boolean;
            /** Okx Permission */
            okx_permission?: ("read_only" | "unknown") | null;
        };
        /** SectorExposureItem */
        SectorExposureItem: {
            /** Notional */
            notional: string;
            /** Sector */
            sector: string;
            /** Weight Pct */
            weight_pct: string;
        };
        /**
         * SettingsResponse
         * @example {
         *       "data_sources": {
         *         "equity": {
         *           "provider": "yahoo",
         *           "scheduler": {
         *             "minute": "1m"
         *           },
         *           "symbols": [
         *             "SPY",
         *             "QQQ"
         *           ]
         *         },
         *         "failure_count": 0,
         *         "macro": {
         *           "scheduler": {
         *             "minute": "1m"
         *           },
         *           "series": {
         *             "us10y": {
         *               "daily": "treasury",
         *               "minute": "yahoo"
         *             },
         *             "us2y": {
         *               "daily": "treasury"
         *             },
         *             "vix": {
         *               "daily": "cboe",
         *               "minute": "yahoo"
         *             }
         *           }
         *         },
         *         "subscribed_instruments": []
         *       },
         *       "display": {
         *         "color_scheme": "system",
         *         "default_bar": "1d",
         *         "home_layout": "cockpit",
         *         "homepage_pinned": [],
         *         "price_precision": 2
         *       },
         *       "execution": {
         *         "auto_trading_enabled": false
         *       },
         *       "notifications": {
         *         "channels": [
         *           "browser"
         *         ],
         *         "subscriptions": {
         *           "browser": {
         *             "min_severity": "info",
         *             "types": [
         *               "indicator",
         *               "price",
         *               "risk",
         *               "strategy",
         *               "data",
         *               "market",
         *               "watchlist"
         *             ]
         *           },
         *           "telegram": {
         *             "min_severity": "warning",
         *             "types": [
         *               "risk",
         *               "strategy"
         *             ]
         *           },
         *           "webhook": {
         *             "min_severity": "warning",
         *             "types": []
         *           }
         *         },
         *         "telegram": {
         *           "chat_id": "",
         *           "token_configured": false
         *         },
         *         "webhook": {
         *           "secret_configured": false,
         *           "url": ""
         *         }
         *       },
         *       "risk_defaults": {
         *         "default_leverage": "3",
         *         "risk_budget_per_trade": "100",
         *         "stop_rule": "fixed_pct",
         *         "warning_threshold": "80"
         *       },
         *       "secrets": {
         *         "okx_configured": false
         *       },
         *       "updated_at": "2026-11-15T06:10:00Z"
         *     }
         */
        SettingsResponse: {
            data_sources: components["schemas"]["DataSourceSettings"];
            display: components["schemas"]["DisplaySettings"];
            execution: components["schemas"]["ExecutionSettings"];
            notifications: components["schemas"]["NotificationSettings"];
            risk_defaults: components["schemas"]["RiskDefaults"];
            secrets: components["schemas"]["SecretSettings"];
            /** Updated At */
            updated_at: string;
        };
        /**
         * SettingsUpdateRequest
         * @description 分组级部分更新，至少提交一项；`secrets` 只读，不在本模型里。
         */
        SettingsUpdateRequest: {
            data_sources?: components["schemas"]["DataSourceSettingsUpdate"] | null;
            display?: components["schemas"]["DisplaySettingsUpdate"] | null;
            exchange?: components["schemas"]["ExchangeSettingsUpdate"] | null;
            execution?: components["schemas"]["ExecutionSettings"] | null;
            notifications?: components["schemas"]["NotificationSettingsUpdate"] | null;
            risk_defaults?: components["schemas"]["RiskDefaults"] | null;
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
        /**
         * StrategyAutoExecutionRuntime
         * @description 自动执行开关的真实取值；v6 只保存状态，不产生真实订单。
         */
        StrategyAutoExecutionRuntime: {
            /** Detail */
            detail: string;
            /** Enabled */
            enabled: boolean;
        };
        /**
         * StrategyBacktestSummary
         * @description 列表与详情里的最近一次回测摘要；指标已是百分数。
         */
        StrategyBacktestSummary: {
            /**
             * Backtest End Date
             * Format: date
             */
            backtest_end_date: string;
            /**
             * Backtest Start Date
             * Format: date
             */
            backtest_start_date: string;
            /** Created At */
            created_at: string;
            /**
             * Data Source
             * @enum {string}
             */
            data_source: "okx" | "okx_spot" | "okx_swap";
            /** Max Drawdown Pct */
            max_drawdown_pct: string;
            /** Run Id */
            run_id: string;
            /** Strategy Version Id */
            strategy_version_id: string;
            /** Total Return Pct */
            total_return_pct: string;
            /** Trade Count */
            trade_count: number;
        };
        /** StrategyCreateRequest */
        StrategyCreateRequest: {
            /** Category */
            category: string;
            /** Change Note */
            change_note?: string | null;
            /** Cost Model */
            cost_model?: {
                [key: string]: unknown;
            } | null;
            /** Description */
            description?: string | null;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /** Instrument Ids */
            instrument_ids: string[];
            /** Name */
            name: string;
            /** Parameters */
            parameters?: {
                [key: string]: unknown;
            };
            /** Position Sizing */
            position_sizing?: {
                [key: string]: unknown;
            } | null;
            /** Rule Json */
            rule_json: {
                [key: string]: unknown;
            };
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
        };
        /**
         * StrategyCreatedResponse
         * @example {
         *       "created_at": "2026-11-08T02:15:00Z",
         *       "id": "st_0001",
         *       "status": "draft",
         *       "version_id": "sv_0001"
         *     }
         */
        StrategyCreatedResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "validated" | "enabled" | "paused" | "archived";
            /** Version Id */
            version_id: string;
        };
        /**
         * StrategyDetail
         * @example {
         *       "category": "directional",
         *       "cost_model": {
         *         "fee_bps": "10",
         *         "slippage_bps": "5"
         *       },
         *       "created_at": "2026-11-08T02:15:00Z",
         *       "current_version": 1,
         *       "current_version_id": "sv_0001",
         *       "description": "均线趋势跟随",
         *       "direction": "long_only",
         *       "id": "st_0001",
         *       "instrument_ids": [
         *         "XAAPL-USDT"
         *       ],
         *       "latest_backtest": {
         *         "backtest_end_date": "2026-11-01",
         *         "backtest_start_date": "2026-10-01",
         *         "created_at": "2026-11-10T01:20:00Z",
         *         "data_source": "okx_spot",
         *         "max_drawdown_pct": "6.12",
         *         "run_id": "bt_0001",
         *         "strategy_version_id": "sv_0001",
         *         "total_return_pct": "12.4055",
         *         "trade_count": 37
         *       },
         *       "name": "AAPL 趋势",
         *       "parameters": {
         *         "fast": 20,
         *         "slow": 60
         *       },
         *       "position_sizing": {
         *         "max_positions": 3,
         *         "type": "equal_weight",
         *         "weight": 0.3333
         *       },
         *       "rule_json": {
         *         "direction": "long_only",
         *         "entry": {
         *           "all": [
         *             {
         *               "left": "MA(20)",
         *               "op": ">",
         *               "right": "MA(60)"
         *             }
         *           ]
         *         },
         *         "exit": {
         *           "any": [
         *             {
         *               "left": "MA(20)",
         *               "op": "<",
         *               "right": "MA(60)"
         *             }
         *           ]
         *         },
         *         "position_sizing": {
         *           "max_positions": 3,
         *           "type": "equal_weight",
         *           "weight": 0.3333
         *         },
         *         "timeframe": "1d"
         *       },
         *       "status": "draft",
         *       "timeframe": "1d",
         *       "updated_at": "2026-11-10T07:00:00Z",
         *       "versions": [
         *         {
         *           "change_note": "初始版本",
         *           "created_at": "2026-11-08T02:15:00Z",
         *           "direction": "long_only",
         *           "timeframe": "1d",
         *           "version": 1,
         *           "version_id": "sv_0001"
         *         }
         *       ]
         *     }
         */
        StrategyDetail: {
            /** Category */
            category: string;
            /** Cost Model */
            cost_model?: {
                [key: string]: unknown;
            } | null;
            /** Created At */
            created_at: string;
            /** Current Version */
            current_version: number;
            /** Current Version Id */
            current_version_id: string;
            /** Description */
            description?: string | null;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /** Id */
            id: string;
            /** Instrument Ids */
            instrument_ids: string[];
            latest_backtest?: components["schemas"]["StrategyBacktestSummary"] | null;
            /** Name */
            name: string;
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            /** Position Sizing */
            position_sizing?: {
                [key: string]: unknown;
            } | null;
            /** Rule Json */
            rule_json: {
                [key: string]: unknown;
            };
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "validated" | "enabled" | "paused" | "archived";
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Updated At */
            updated_at: string;
            /** Versions */
            versions: components["schemas"]["StrategyVersionSummary"][];
        };
        /** StrategyInstrumentUpdateRequest */
        StrategyInstrumentUpdateRequest: {
            /** Instrument Ids */
            instrument_ids: string[];
        };
        /**
         * StrategyListResponse
         * @example {
         *       "items": [
         *         {
         *           "category": "directional",
         *           "created_at": "2026-11-08T02:15:00Z",
         *           "current_version": 1,
         *           "current_version_id": "sv_0001",
         *           "description": "均线趋势跟随",
         *           "direction": "long_only",
         *           "id": "st_0001",
         *           "instrument_count": 1,
         *           "latest_backtest": {
         *             "backtest_end_date": "2026-11-01",
         *             "backtest_start_date": "2026-10-01",
         *             "created_at": "2026-11-10T01:20:00Z",
         *             "data_source": "okx_spot",
         *             "max_drawdown_pct": "6.12",
         *             "run_id": "bt_0001",
         *             "strategy_version_id": "sv_0001",
         *             "total_return_pct": "12.4055",
         *             "trade_count": 37
         *           },
         *           "name": "AAPL 趋势",
         *           "status": "draft",
         *           "timeframe": "1d",
         *           "updated_at": "2026-11-10T07:00:00Z"
         *         }
         *       ]
         *     }
         */
        StrategyListResponse: {
            /** Items */
            items: components["schemas"]["StrategySummary"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /**
         * StrategyRuntimeResponse
         * @description 策略页运行状态：信号扫描、自动执行与后端检查时间。
         * @example {
         *       "auto_execution": {
         *         "detail": "自动执行默认关闭，只保存开关，不产生真实订单",
         *         "enabled": false
         *       },
         *       "checked_at": "2026-11-16T01:30:00Z",
         *       "signal_scan": {
         *         "detail": "策略信号扫描尚未实现",
         *         "status": "not_implemented"
         *       }
         *     }
         */
        StrategyRuntimeResponse: {
            auto_execution: components["schemas"]["StrategyAutoExecutionRuntime"];
            /** Checked At */
            checked_at: string;
            signal_scan: components["schemas"]["StrategySignalScanRuntime"];
        };
        /**
         * StrategySignalScanRuntime
         * @description 信号扫描状态；当前版本没有扫描任务，明确报告未实现。
         */
        StrategySignalScanRuntime: {
            /** Detail */
            detail: string;
            /**
             * Status
             * @constant
             */
            status: "not_implemented";
        };
        /** StrategySummary */
        StrategySummary: {
            /** Category */
            category: string;
            /** Created At */
            created_at: string;
            /** Current Version */
            current_version: number;
            /** Current Version Id */
            current_version_id: string;
            /** Description */
            description?: string | null;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /** Id */
            id: string;
            /** Instrument Count */
            instrument_count: number;
            latest_backtest?: components["schemas"]["StrategyBacktestSummary"] | null;
            /** Name */
            name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "validated" | "enabled" | "paused" | "archived";
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Updated At */
            updated_at: string;
        };
        /**
         * StrategyUpdateRequest
         * @description 只改提交的字段；出现任一版本字段时新建下一版。
         */
        StrategyUpdateRequest: {
            /** Category */
            category?: string | null;
            /** Change Note */
            change_note?: string | null;
            /** Cost Model */
            cost_model?: {
                [key: string]: unknown;
            } | null;
            /** Description */
            description?: string | null;
            /** Direction */
            direction?: ("long_only" | "short_only" | "long_short") | null;
            /** Instrument Ids */
            instrument_ids?: string[] | null;
            /** Name */
            name?: string | null;
            /** Parameters */
            parameters?: {
                [key: string]: unknown;
            } | null;
            /** Position Sizing */
            position_sizing?: {
                [key: string]: unknown;
            } | null;
            /** Rule Json */
            rule_json?: {
                [key: string]: unknown;
            } | null;
            /** Status */
            status?: ("draft" | "validated" | "enabled" | "paused" | "archived") | null;
            /** Timeframe */
            timeframe?: ("1m" | "5m" | "15m" | "1h" | "4h" | "1d") | null;
        };
        /**
         * StrategyUpdatedResponse
         * @example {
         *       "id": "st_0001",
         *       "status": "draft",
         *       "updated_at": "2026-11-10T07:00:00Z",
         *       "version_id": "sv_0002"
         *     }
         */
        StrategyUpdatedResponse: {
            /** Id */
            id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "draft" | "validated" | "enabled" | "paused" | "archived";
            /** Updated At */
            updated_at: string;
            /** Version Id */
            version_id: string;
        };
        /**
         * StrategyVersionCreateRequest
         * @description 新建下一版：未提交的字段沿用当前版本。
         */
        StrategyVersionCreateRequest: {
            /** Change Note */
            change_note?: string | null;
            /** Cost Model */
            cost_model?: {
                [key: string]: unknown;
            } | null;
            /** Direction */
            direction?: ("long_only" | "short_only" | "long_short") | null;
            /** Instrument Ids */
            instrument_ids?: string[] | null;
            /** Parameters */
            parameters?: {
                [key: string]: unknown;
            } | null;
            /** Position Sizing */
            position_sizing?: {
                [key: string]: unknown;
            } | null;
            /** Rule Json */
            rule_json?: {
                [key: string]: unknown;
            } | null;
            /** Timeframe */
            timeframe?: ("1m" | "5m" | "15m" | "1h" | "4h" | "1d") | null;
        };
        /**
         * StrategyVersionDetail
         * @example {
         *       "change_note": "初始版本",
         *       "cost_model": {
         *         "fee_bps": "10",
         *         "slippage_bps": "5"
         *       },
         *       "created_at": "2026-11-08T02:15:00Z",
         *       "direction": "long_only",
         *       "instrument_ids": [
         *         "XAAPL-USDT"
         *       ],
         *       "parameters": {
         *         "fast": 20,
         *         "slow": 60
         *       },
         *       "position_sizing": {
         *         "max_positions": 3,
         *         "type": "equal_weight",
         *         "weight": 0.3333
         *       },
         *       "rule_json": {
         *         "direction": "long_only",
         *         "entry": {
         *           "all": [
         *             {
         *               "left": "MA(20)",
         *               "op": ">",
         *               "right": "MA(60)"
         *             }
         *           ]
         *         },
         *         "exit": {
         *           "any": [
         *             {
         *               "left": "MA(20)",
         *               "op": "<",
         *               "right": "MA(60)"
         *             }
         *           ]
         *         },
         *         "position_sizing": {
         *           "max_positions": 3,
         *           "type": "equal_weight",
         *           "weight": 0.3333
         *         },
         *         "timeframe": "1d"
         *       },
         *       "strategy_id": "st_0001",
         *       "timeframe": "1d",
         *       "version": 1,
         *       "version_id": "sv_0001"
         *     }
         */
        StrategyVersionDetail: {
            /** Change Note */
            change_note?: string | null;
            /** Cost Model */
            cost_model?: {
                [key: string]: unknown;
            } | null;
            /** Created At */
            created_at: string;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /** Instrument Ids */
            instrument_ids: string[];
            /** Parameters */
            parameters: {
                [key: string]: unknown;
            };
            /** Position Sizing */
            position_sizing?: {
                [key: string]: unknown;
            } | null;
            /** Rule Json */
            rule_json: {
                [key: string]: unknown;
            };
            /** Strategy Id */
            strategy_id: string;
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Version */
            version: number;
            /** Version Id */
            version_id: string;
        };
        /**
         * StrategyVersionListResponse
         * @example {
         *       "items": [
         *         {
         *           "change_note": "初始版本",
         *           "cost_model": {
         *             "fee_bps": "10",
         *             "slippage_bps": "5"
         *           },
         *           "created_at": "2026-11-08T02:15:00Z",
         *           "direction": "long_only",
         *           "instrument_ids": [
         *             "XAAPL-USDT"
         *           ],
         *           "parameters": {
         *             "fast": 20,
         *             "slow": 60
         *           },
         *           "position_sizing": {
         *             "max_positions": 3,
         *             "type": "equal_weight",
         *             "weight": 0.3333
         *           },
         *           "rule_json": {
         *             "direction": "long_only",
         *             "entry": {
         *               "all": [
         *                 {
         *                   "left": "MA(20)",
         *                   "op": ">",
         *                   "right": "MA(60)"
         *                 }
         *               ]
         *             },
         *             "exit": {
         *               "any": [
         *                 {
         *                   "left": "MA(20)",
         *                   "op": "<",
         *                   "right": "MA(60)"
         *                 }
         *               ]
         *             },
         *             "position_sizing": {
         *               "max_positions": 3,
         *               "type": "equal_weight",
         *               "weight": 0.3333
         *             },
         *             "timeframe": "1d"
         *           },
         *           "strategy_id": "st_0001",
         *           "timeframe": "1d",
         *           "version": 1,
         *           "version_id": "sv_0001"
         *         }
         *       ],
         *       "total": 1
         *     }
         */
        StrategyVersionListResponse: {
            /** Items */
            items: components["schemas"]["StrategyVersionDetail"][];
            /** Total */
            total: number;
        };
        /** StrategyVersionSummary */
        StrategyVersionSummary: {
            /** Change Note */
            change_note?: string | null;
            /** Created At */
            created_at: string;
            /**
             * Direction
             * @enum {string}
             */
            direction: "long_only" | "short_only" | "long_short";
            /**
             * Timeframe
             * @enum {string}
             */
            timeframe: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
            /** Version */
            version: number;
            /** Version Id */
            version_id: string;
        };
        /**
         * SystemComponent
         * @description 一个系统组件的最新状态；错误只给摘要，不带上游原始应答。
         */
        SystemComponent: {
            /** Detail */
            detail: string | null;
            /** Error */
            error: string | null;
            /** Last Success At */
            last_success_at: string | null;
            /** Name */
            name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "stale" | "error" | "unconfigured";
        };
        /**
         * SystemHealthResponse
         * @description 系统健康总览；单项异常不影响其他项，整体状态降为 `degraded`。
         * @example {
         *       "checked_at": "2026-11-15T06:10:00Z",
         *       "components": [
         *         {
         *           "last_success_at": "2026-11-15T06:10:00Z",
         *           "name": "database",
         *           "status": "ok"
         *         },
         *         {
         *           "detail": "candles 最近一次同步成功且仍在时效内",
         *           "last_success_at": "2026-11-15T06:05:00Z",
         *           "name": "okx_rest",
         *           "status": "ok"
         *         }
         *       ],
         *       "status": "ok"
         *     }
         */
        SystemHealthResponse: {
            /** Checked At */
            checked_at: string;
            /** Components */
            components: components["schemas"]["SystemComponent"][];
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "degraded";
        };
        /**
         * SystemSyncRequest
         * @description 手动触发一次 OKX 行情同步；`bar` 与 `days` 只对 `candles` 生效。
         */
        SystemSyncRequest: {
            /** Bar */
            bar?: ("1m" | "5m" | "15m" | "1h" | "4h" | "1d") | null;
            /** Dataset */
            dataset: string;
            /** Days */
            days?: number | null;
            /** Instrument Ids */
            instrument_ids?: string[];
        };
        /**
         * SystemSyncResponse
         * @description 同步任务结果；任务流水同时写入 `data_sync_jobs`。
         * @example {
         *       "job_id": "job_0123456789abcdef01234567",
         *       "rows": 4,
         *       "status": "succeeded"
         *     }
         */
        SystemSyncResponse: {
            /** Error */
            error?: string | null;
            /** Job Id */
            job_id: string;
            /** Rows */
            rows: number;
            /** Status */
            status: string;
        };
        /**
         * TelegramSettings
         * @description Telegram 接收方：`chat_id` 可读写，token 只报「是否已配置」。
         */
        TelegramSettings: {
            /**
             * Chat Id
             * @default
             */
            chat_id: string;
            /**
             * Token Configured
             * @default false
             */
            token_configured: boolean;
        };
        /**
         * TelegramSettingsUpdate
         * @description Telegram 可写字段：只有 `chat_id`。空字符串表示「清空接收方」。
         */
        TelegramSettingsUpdate: {
            /**
             * Chat Id
             * @default
             */
            chat_id: string;
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
        /** TrendIndicators */
        TrendIndicators: {
            /** Close */
            close?: string | null;
            /** Ma20 */
            ma20?: string | null;
            /** Ma20 Slope Pct */
            ma20_slope_pct?: string | null;
            /** Ma60 */
            ma60?: string | null;
            /** Ma60 Slope Pct */
            ma60_slope_pct?: string | null;
            /** Price Vs Ma20 Pct */
            price_vs_ma20_pct?: string | null;
            /** Price Vs Ma60 Pct */
            price_vs_ma60_pct?: string | null;
            /** Slope Window */
            slope_window: number;
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
        /** VolatilityIndicators */
        VolatilityIndicators: {
            /** Atr14 */
            atr14?: string | null;
            /** Atr Pct */
            atr_pct?: string | null;
            /** Atr Pct Avg20 */
            atr_pct_avg20?: string | null;
        };
        /** VolumeIndicators */
        VolumeIndicators: {
            /** Average20 */
            average20?: string | null;
            /** Current */
            current?: string | null;
            /** Relative */
            relative?: string | null;
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
        /**
         * WatchlistItem
         * @description 自选列表一行：日线快照、技术指标、数据覆盖与关联运行态。
         *
         *     价格与派生指标都可能为 `null`：该行没有日线时如实留空，不补 0。
         *     `data_status` 区分「没有 K 线」与「有 K 线但指标历史不足」。
         * @example {
         *       "atr_pct_14": "2.3",
         *       "candle_count": 846,
         *       "change_pct_24h": "1.86",
         *       "data_status": "ok",
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
         *       "last_candle_at": "2026-11-12T16:00:00Z",
         *       "last_price": "231.42",
         *       "last_signal": {
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
         *       "rsi_14": "61.4",
         *       "strategy": {
         *         "enabled": true,
         *         "execution_mode": "paper",
         *         "instance_id": "si_0001",
         *         "name": "AAPL 趋势",
         *         "status": "live_running"
         *       },
         *       "trend": "bullish",
         *       "volume_24h_quote": "4821334.55"
         *     }
         */
        WatchlistItem: {
            /** Atr Pct 14 */
            atr_pct_14: string | null;
            /** Candle Count */
            candle_count: number;
            /** Change Pct 24H */
            change_pct_24h: string | null;
            /**
             * Data Status
             * @enum {string}
             */
            data_status: "ok" | "partial" | "missing";
            /** Group */
            group: string;
            instrument: components["schemas"]["InstrumentInfo"];
            /** Last Candle At */
            last_candle_at: string | null;
            /** Last Price */
            last_price: string | null;
            last_signal?: components["schemas"]["Signal"] | null;
            /** Rsi 14 */
            rsi_14: string | null;
            strategy?: components["schemas"]["WatchlistStrategy"] | null;
            /** Trend */
            trend: ("bullish" | "bearish" | "neutral") | null;
            /** Volume 24H Quote */
            volume_24h_quote: string | null;
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
         *           "atr_pct_14": "2.3",
         *           "candle_count": 846,
         *           "change_pct_24h": "1.86",
         *           "data_status": "ok",
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
         *           "last_candle_at": "2026-11-12T16:00:00Z",
         *           "last_price": "231.42",
         *           "last_signal": {
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
         *           "rsi_14": "61.4",
         *           "strategy": {
         *             "enabled": true,
         *             "execution_mode": "paper",
         *             "instance_id": "si_0001",
         *             "name": "AAPL 趋势",
         *             "status": "live_running"
         *           },
         *           "trend": "bullish",
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
        /**
         * WatchlistStrategy
         * @description 自选行关联的运行策略；一个标的可能被多个实例引用，这里只显示最近建立的一个。
         */
        WatchlistStrategy: {
            /** Enabled */
            enabled: boolean;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode: "manual" | "paper" | "live";
            /** Instance Id */
            instance_id: string;
            /** Name */
            name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "opportunity_discovery" | "strategy_generation" | "pending_review" | "backtested" | "validated" | "paper_trading" | "live_authorized" | "live_running" | "rejected";
        };
        /** WatchlistUpdateRequest */
        WatchlistUpdateRequest: {
            /** Group */
            group: string;
        };
        /**
         * WebhookSettings
         * @description Webhook 接收方：地址可读写，签名密钥只报「是否已配置」。
         */
        WebhookSettings: {
            /**
             * Secret Configured
             * @default false
             */
            secret_configured: boolean;
            /**
             * Url
             * @default
             */
            url: string;
        };
        /**
         * WebhookSettingsUpdate
         * @description Webhook 可写字段：只有接收地址，必须是 http 或 https。
         */
        WebhookSettingsUpdate: {
            /**
             * Url
             * @default
             */
            url: string;
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
    get_account_equity_curve_api_account_equity_curve_get: {
        parameters: {
            query?: {
                range?: "1d" | "1w" | "1m" | "6m" | "1y";
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
                    "application/json": components["schemas"]["EquityCurveResponse"];
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
    get_account_summary_api_account_summary_get: {
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
                    "application/json": components["schemas"]["AccountSummaryResponse"];
                };
            };
        };
    };
    sync_account_snapshot_api_account_sync_post: {
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
                    "application/json": components["schemas"]["AccountSyncResponse"];
                };
            };
        };
    };
    get_activity_api_activity_get: {
        parameters: {
            query?: {
                event_type?: string | null;
                object_type?: string | null;
                from?: string | null;
                to?: string | null;
                limit?: number;
                cursor?: string | null;
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
                    "application/json": components["schemas"]["ActivityListResponse"];
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
    post_ai_summary_api_ai_summary_post: {
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
                    "application/json": components["schemas"]["AiSummaryResponse"];
                };
            };
        };
    };
    get_alerts_api_alerts_get: {
        parameters: {
            query?: {
                status?: string | null;
                type?: string | null;
                severity?: string | null;
                instrument_id?: string | null;
                limit?: number;
                cursor?: string | null;
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
                    "application/json": components["schemas"]["AlertListResponse"];
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
    patch_alert_api_alerts__alert_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AlertStatusUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertItem"];
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
                data_source: "okx" | "okx_spot" | "okx_swap";
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
                    "application/json": components["schemas"]["BacktestBatchResponse"];
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
                data_source: "okx" | "okx_spot" | "okx_swap";
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
    get_backtest_chart_api_backtests__run_id__chart_get: {
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
                    "application/json": components["schemas"]["BacktestChartResponse"];
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
    get_backtest_equity_api_backtests__run_id__equity_get: {
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
                    "application/json": components["schemas"]["BacktestEquityResponse"];
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
    get_backtest_replay_api_backtests__run_id__replay_get: {
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
                    "application/json": components["schemas"]["BacktestReplayResponse"];
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
    list_backtest_trades_api_backtests__run_id__trades_get: {
        parameters: {
            query?: {
                side?: string | null;
                result?: string | null;
                inst_id?: string | null;
                limit?: number;
                offset?: number;
            };
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
                    "application/json": components["schemas"]["BacktestTradeListResponse"];
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
    export_backtest_trades_api_backtests__run_id__trades_csv_get: {
        parameters: {
            query?: {
                side?: string | null;
                result?: string | null;
                inst_id?: string | null;
            };
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
                    "text/csv": string;
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
    get_dashboard_summary_api_dashboard_summary_get: {
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
                    "application/json": components["schemas"]["DashboardSummaryResponse"];
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
    get_instrument_analysis_api_instruments__inst_id__analysis_get: {
        parameters: {
            query?: {
                bar?: "1d" | "4h" | "1h";
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
                    "application/json": components["schemas"]["InstrumentAnalysisResponse"];
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
                source: "okx" | "okx_spot" | "okx_swap";
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
    list_instrument_strategies_api_instruments__inst_id__strategies_get: {
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
                    "application/json": components["schemas"]["InstrumentStrategyListResponse"];
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
    sync_instrument_api_instruments__inst_id__sync_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inst_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["InstrumentSyncRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstrumentSyncResponse"];
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
    get_macro_overview_api_macro_overview_get: {
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
                    "application/json": components["schemas"]["MacroOverviewResponse"];
                };
            };
        };
    };
    post_macro_sync_api_macro_sync_post: {
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
                    "application/json": components["schemas"]["MacroSyncResponse"];
                };
            };
        };
    };
    get_manual_positions_api_manual_positions_get: {
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
                    "application/json": components["schemas"]["ManualPositionListResponse"];
                };
            };
        };
    };
    create_manual_position_endpoint_api_manual_positions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ManualPositionCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ManualPositionItem"];
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
    delete_manual_position_endpoint_api_manual_positions__position_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                position_id: string;
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
    update_manual_position_endpoint_api_manual_positions__position_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                position_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ManualPositionUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ManualPositionItem"];
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
    get_manual_trades_api_manual_positions__position_id__trades_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                position_id: string;
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
                    "application/json": components["schemas"]["ManualTradeListResponse"];
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
    add_manual_trade_endpoint_api_manual_positions__position_id__trades_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                position_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ManualTradeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ManualTradeItem"];
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
    get_market_breadth_api_market_breadth_get: {
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
                    "application/json": components["schemas"]["MarketBreadthResponse"];
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
    get_market_snapshot_api_market_overview_get: {
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
                    "application/json": components["schemas"]["MarketSnapshotResponse"];
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
    get_positions_api_positions_get: {
        parameters: {
            query?: {
                source?: ("exchange" | "manual") | null;
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
                    "application/json": components["schemas"]["MergedPositionsResponse"];
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
    get_position_cards_api_positions_cards_get: {
        parameters: {
            query?: {
                range?: "1d" | "1w" | "1m" | "6m" | "1y";
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
                    "application/json": components["schemas"]["PositionCardsResponse"];
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
    get_exchange_positions_api_positions_exchange_get: {
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
                    "application/json": components["schemas"]["ExchangePositionsResponse"];
                };
            };
        };
    };
    get_instrument_orders_api_positions__inst_id__orders_get: {
        parameters: {
            query?: {
                scope?: "all" | "open" | "history";
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
                    "application/json": components["schemas"]["OrderHistoryResponse"];
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
    put_position_risk_config_api_positions__position_ref__risk_config_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                position_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskConfigUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PositionRiskConfigResponse"];
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
    get_research_notes_api_research_notes_get: {
        parameters: {
            query?: {
                type?: string | null;
                related_instrument_id?: string | null;
                related_strategy_id?: string | null;
                related_backtest_id?: string | null;
                from?: string | null;
                to?: string | null;
                limit?: number;
                cursor?: string | null;
                sort?: string;
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
                    "application/json": components["schemas"]["ResearchNoteListResponse"];
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
    post_research_note_api_research_notes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResearchNoteCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchNoteCreatedResponse"];
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
    get_research_note_api_research_notes__note_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                note_id: string;
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
                    "application/json": components["schemas"]["ResearchNoteItem"];
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
    put_research_note_api_research_notes__note_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                note_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResearchNoteUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResearchNoteUpdatedResponse"];
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
    remove_research_note_api_research_notes__note_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                note_id: string;
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
    list_risk_event_records_api_risk_events_get: {
        parameters: {
            query?: {
                instance_id?: string | null;
                inst_id?: string | null;
                rule?: string | null;
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
                    "application/json": components["schemas"]["RiskEventListResponse"];
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
    resolve_risk_event_record_api_risk_events__event_id__resolve_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                event_id: string;
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
                    "application/json": components["schemas"]["RiskEvent"];
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
    get_risk_exposure_api_risk_exposure_get: {
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
                    "application/json": components["schemas"]["RiskExposureResponse"];
                };
            };
        };
    };
    get_risk_notify_config_api_risk_notify_config_get: {
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
                    "application/json": components["schemas"]["RiskNotifyConfigResponse"];
                };
            };
        };
    };
    put_risk_notify_config_api_risk_notify_config_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskNotifyConfigUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskNotifyConfigResponse"];
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
    patch_settings_document_api_settings_patch: {
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
    get_notification_deliveries_api_settings_notifications_deliveries_get: {
        parameters: {
            query?: {
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
                    "application/json": components["schemas"]["DeliveryListResponse"];
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
    test_notification_channel_api_settings_notifications_test_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NotificationChannelTestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationChannelTestResponse"];
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
    list_strategies_endpoint_api_strategies_get: {
        parameters: {
            query?: {
                status?: string | null;
                category?: string | null;
                limit?: number;
                cursor?: string | null;
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
                    "application/json": components["schemas"]["StrategyListResponse"];
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
    create_strategy_endpoint_api_strategies_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyCreatedResponse"];
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
    get_strategy_runtime_api_strategies_runtime_get: {
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
                    "application/json": components["schemas"]["StrategyRuntimeResponse"];
                };
            };
        };
    };
    get_strategy_endpoint_api_strategies__strategy_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                strategy_id: string;
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
                    "application/json": components["schemas"]["StrategyDetail"];
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
    update_strategy_endpoint_api_strategies__strategy_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                strategy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyUpdatedResponse"];
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
    list_strategy_versions_api_strategies__strategy_id__versions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                strategy_id: string;
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
                    "application/json": components["schemas"]["StrategyVersionListResponse"];
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
    create_strategy_version_api_strategies__strategy_id__versions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                strategy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyVersionCreateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyVersionDetail"];
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
    update_strategy_version_instruments_api_strategies__strategy_id__versions__version__instruments_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                strategy_id: string;
                version: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategyInstrumentUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategyVersionDetail"];
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
    get_system_health_api_system_health_get: {
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
                    "application/json": components["schemas"]["SystemHealthResponse"];
                };
            };
        };
    };
    post_system_sync_api_system_sync_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SystemSyncRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemSyncResponse"];
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
