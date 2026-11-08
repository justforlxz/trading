"""只读术语表: 定义式问题的唯一事实来源。

术语表是**静态**的: 不从数据库、模型或网络取任何内容, 因此概念类回答天然可复现、
可审计, 也不受「域数据是否可用」影响。术语未收录时不作答 (`concept_unknown`),
而不是让模型自由解释。
"""

from __future__ import annotations

GLOSSARY: dict[str, str] = {
    "多单": "预期价格上涨而持有的买入方向仓位; 价格下跌时亏损。",
    "空单": "预期价格下跌而持有的卖出方向仓位; 价格上涨时亏损。",
    "做多": "买入开仓, 持有正向敞口, 赚取价格上涨的收益。",
    "做空": "卖出开仓, 持有负向敞口, 赚取价格下跌的收益。",
    "建仓": "首次买入或卖出建立仓位; 成本指成交均价与手续费合计。",
    "换仓": "平掉现有仓位并在另一标的上重新建仓; 会同时产生平仓与开仓成本。",
    "清仓": "把某个标的或组合的仓位全部平掉, 敞口归零。",
    "止损": "价格触及预设的亏损阈值时自动平仓, 用于限制单笔损失。",
    "止盈": "价格触及预设的盈利阈值时自动平仓, 用于锁定收益。",
    "杠杆": "名义敞口与保证金资本的比值; 杠杆越高, 波动被放大越多。",
    "敞口": "尚未平仓的头寸按市价折算的名义金额; 多空相抵后为净敞口。",
    "集中度": "单个标的或单条腿在总敞口中的占比; 占比越高, 单一标的风险越集中。",
    "权重": "一条腿在组合中占用的资金比例, 所有腿的权重决定组合的总敞口。",
    "腿": "组合中的一条独立持仓方向; 多空组合至少包含两条腿。",
    "回测": "用历史行情按策略规则重放交易, 得到收益、回撤与交易次数等指标。",
    "夏普": "年化超额收益与收益波动率的比值; 越高说明单位波动的回报越好。",
    "回撤": "净值从历史峰值下跌的幅度; 最大回撤衡量策略的最坏持有体验。",
}


def resolve_term(question: str) -> str | None:
    """返回问题里**最先出现**的已收录术语; 同位置取更长的词。"""

    best: tuple[int, int, str] | None = None
    for term in GLOSSARY:
        index = question.find(term)
        if index < 0:
            continue
        candidate = (index, -len(term), term)
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[2]


def definition_of(term: str) -> str | None:
    return GLOSSARY.get(term)


__all__ = ["GLOSSARY", "definition_of", "resolve_term"]
