"""动作安全检查 + 正向读取许可的判定矩阵。

只测纯函数 `assess()`, 不落库; 端到端 (403 / 200 answerable=false / 审计) 由
`tests/ai/test_guard.py` 与 `tests/ai/test_query_corpus.py` 覆盖。

判定顺序是固定的: 任一句是祈使句 -> 整体不作答; 只有疑问句才进入读取许可,
未命中许可或无法判断都不给数据。
"""

from __future__ import annotations

import pytest

from app.ai.core import query as query_core

WRITE_CASES: tuple[tuple[str, str], ...] = (
    ("给我卖 100 股", "quantity"),
    ("撤掉所有挂单", "trade"),
    ("把杠杆拉到5倍", "risk"),
    ("把止损上移", "risk"),
    ("清掉仓位", "position"),
    ("给策略1加大资金", "risk"),
    ("直接满仓", "capital"),
    ("把实盘打开", "execution"),
    ("开实盘", "execution"),
    ("把策略\n改成做空", "strategy"),
)

IMPERATIVE_UNCLASSIFIED: tuple[str, ...] = (
    "帮我买点BTC",
    "把 策 略\n改 成 做空",
)


@pytest.mark.parametrize("question,matched", WRITE_CASES)
def test_imperative_with_controlled_object_is_write_forbidden(question: str, matched: str) -> None:
    decision = query_core.assess(question)
    assert decision.answerable is False, question
    assert decision.intent is None, question
    assert decision.refusal == query_core.REFUSAL_WRITE, question
    assert decision.matched == matched, question


@pytest.mark.parametrize("question", IMPERATIVE_UNCLASSIFIED)
def test_imperative_without_object_class_is_not_answerable(question: str) -> None:
    decision = query_core.assess(question)
    assert decision.answerable is False, question
    assert decision.intent is None, question
    assert decision.refusal == query_core.REFUSAL_IMPERATIVE, question


READ_CASES: tuple[tuple[str, str], ...] = (
    ("什么是多单", "concept"),
    ("什么是空单", "concept"),
    ("做多和做空的区别", "concept"),
    ("解释一下多单", "positions"),
    ("我现在有多单吗", "positions"),
    ("建仓成本是多少", "positions"),
    ("换仓成本高吗", "positions"),
    ("持仓盈亏怎么样", "positions"),
    ("解释一下当前行情", "market"),
    ("解释回测 3 的表现", "backtest"),
    ("当前风控敞口是多少", "risk"),
    ("策略 1 的调整历史", "strategy"),
    ("策略 1 的审批记录", "strategy"),
    ("最近的风控事件有哪些", "risk"),
)


@pytest.mark.parametrize("question,intent", READ_CASES)
def test_question_with_positive_license_is_answerable(question: str, intent: str) -> None:
    decision = query_core.assess(question)
    assert decision.answerable is True, question
    assert decision.refusal is None, question
    assert decision.intent == intent, question


UNLICENSED: tuple[str, ...] = (
    "今天天气怎么样",  # 疑问句但没有任何读取许可
)


@pytest.mark.parametrize("question", UNLICENSED)
def test_question_without_license_is_refused(question: str) -> None:
    decision = query_core.assess(question)
    assert decision.answerable is False, question
    assert decision.intent is None, question
    assert decision.refusal == query_core.REFUSAL_UNLICENSED, question


UNROUTED: tuple[str, ...] = (
    "请问今天天气如何",
    "一把梭",
)


@pytest.mark.parametrize("question", UNROUTED)
def test_unrouted_input_is_not_answerable(question: str) -> None:
    decision = query_core.assess(question)
    assert decision.answerable is False, question
    assert decision.refusal in (
        query_core.REFUSAL_UNROUTED,
        query_core.REFUSAL_UNLICENSED,
    ), question


def test_unknown_concept_is_not_answerable() -> None:
    decision = query_core.assess("什么是波动率")
    assert decision.answerable is False
    assert decision.refusal == query_core.REFUSAL_CONCEPT_UNKNOWN


def test_glossary_term_is_echoed_in_decision() -> None:
    assert query_core.assess("什么是多单").matched == "多单"
    assert query_core.assess("做多和做空的区别").matched == "做多"


def test_whitespace_is_removed_for_entity_id_matching() -> None:
    assert query_core.normalize_question("把 策 略\n改\t成 做空") == "把策略改成做空"
    assert query_core.assess("把策\n略改成做空").answerable is False


def test_action_check_always_precedes_attribute_structure() -> None:
    """不变量: 命中处置前缀 + 受控对象 + 变更形态的句子, 无论是否带
    「对象 + 的 + 属性」结构、是否带问号, 都不得获得读取许可。

    这条测试锁的是判定顺序, 不是逐句语料; 属性结构与问句都只是分类特征,
    不能覆盖动作请求。
    """

    prefixes = ("把", "将", "给我")
    targets = ("策略 1", "持仓", "仓位", "风控")
    attributes = ("腿", "权重", "成本", "阈值")
    changes = ("删掉一条", "改成空头", "清掉", "调低", "提高", "去掉一条")
    for prefix in prefixes:
        for target in targets:
            for attribute in attributes:
                for change in changes:
                    sentence = f"{prefix}{target}的{attribute}{change}"
                    decision = query_core.assess(sentence)
                    assert decision.answerable is False, sentence
                    decision_q = query_core.assess(f"{sentence}好吗")
                    assert decision_q.answerable is False, sentence


@pytest.mark.parametrize("subject", ["策略 1", "持仓", "仓位", "风控"])
@pytest.mark.parametrize("attribute", ["腿", "权重", "成本", "阈值"])
@pytest.mark.parametrize(
    "change", ["减少一条", "减一条", "合并", "作废", "下线", "停用", "降低", "提高"]
)
def test_object_first_change_never_answerable(subject: str, attribute: str, change: str) -> None:
    """「对象 + 的 + 属性 + 其它成分」: 属性结构不能单独换来读取许可。"""

    for suffix in ("", "可以吗", "好吗", "行吗", "是两条", "有多少", "有几条"):
        question = f"{subject}的{attribute}{change}{suffix}"
        assert query_core.assess(question).answerable is False, question
