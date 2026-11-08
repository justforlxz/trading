"""只读许可与动作安全检查: 先判动作, 再给许可, 最后才可能读域数据。

三段判定, 顺序固定, 前两段不通过时调用方不得访问任何读端口:

1. **动作安全检查**: 逐句判定, 任一句是祈使/处置句即整体按写/未分类拒绝。
2. **正向读取许可**: 只有疑问句才进入许可判定, 且必须命中 `READ_PATTERNS`
   (或定义式问题的术语表) 才放行; 未命中即 `unlicensed`。
3. **无法判断**: 既不疑问也不祈使的输入一律 `unrouted`, 不给任何域数据。

判定只用**句首/句末锚点**, 不做「句子里出现某词就放行」。受控对象类别只在已经
判定为祈使句之后才使用, 所以那里的包含判断不构成放行后门。

这里只做文本分类: 不读数据、不调模型, 便于穷举单测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.ai.core import glossary

INTENT_CONCEPT = "concept"
INTENT_MARKET = "market"
INTENT_RELATIONS = "relations"
INTENT_STRATEGY = "strategy"
INTENT_BACKTEST = "backtest"
INTENT_RISK = "risk"
INTENT_POSITIONS = "positions"

REFUSAL_WRITE = "write_forbidden"
REFUSAL_IMPERATIVE = "imperative_unclassified"
REFUSAL_UNROUTED = "unrouted"
REFUSAL_UNLICENSED = "unlicensed"
REFUSAL_CONCEPT_UNKNOWN = "concept_unknown"

REFUSAL_MESSAGES: dict[str, str] = {
    REFUSAL_WRITE: "只读助手不执行写操作; 下单、改策略、改风控、审批与启动实盘请走人工流程",
    REFUSAL_IMPERATIVE: "无法判定请求类型, 未执行任何操作。",
    REFUSAL_UNROUTED: "无法判定请求类型, 未执行任何操作。",
    REFUSAL_UNLICENSED: "未获得读取许可, 无法据此作答。",
    REFUSAL_CONCEPT_UNKNOWN: "术语表未收录该概念, 无法据此作答。",
}

# 疑问句的句首锚点: 只有出现在句首(可带礼貌前缀)才算疑问。
QUESTION_PREFIXES: tuple[str, ...] = (
    "什么",
    "啥",
    "哪",
    "谁",
    "为什么",
    "怎么",
    "如何",
    "是否",
    "请问",
    "解释",
    "解读",
    "说明",
    "介绍",
    "分析",
    "对比",
    "多少",
    "几",
    "区别",
)

# 疑问句的句末锚点。
QUESTION_SUFFIXES: tuple[str, ...] = (
    "吗",
    "呢",
    "是多少",
    "是什么",
    "多少钱",
    "有什么区别",
    "的区别",
    "是什么意思",
    "怎么样",
    "怎么办",
)

# 句末是问号时直接算疑问句(切句时保留终止符)。
QUESTION_TERMINATORS: tuple[str, ...] = ("\uff1f", "?")

# 定义式问法: 句首或句末命中即走术语表, 不读域数据。
DEFINITION_PREFIXES: tuple[str, ...] = (
    "什么是",
    "是什么",
    "是什么意思",
    "的含义",
    "的定义",
    "的区别",
)
DEFINITION_SUFFIXES: tuple[str, ...] = ("的区别", "是什么意思")

# 礼貌/人称前缀不是指令本身, 判定疑问锚点前先剥离。
POLITENESS_PREFIXES: tuple[str, ...] = (
    "可不可以",
    "能不能",
    "要不要",
    "能否",
    "可以",
    "我要",
    "我想",
    "想要",
    "请问",
    "麻烦",
    "帮我",
    "给我",
    "替我",
    "让我",
    "请",
    "能",
    "想",
)

# 祈使/处置句的句首锚点。
IMPERATIVE_PREFIXES: tuple[str, ...] = (
    "给我",
    "替我",
    "让我",
    "麻烦",
    "把",
    "将",
    "给",
    "替",
    "让",
    "请",
    "帮",
    "你",
    "马上",
    "直接",
    "先",
    "立刻",
    "立即",
)

# 祈使句的句首动作词根。
ACTION_ROOTS: tuple[str, ...] = (
    "买",
    "卖",
    "平",
    "清",
    "撤",
    "加",
    "减",
    "开",
    "关",
    "调",
    "改",
    "设",
    "移",
    "拉",
    "换",
    "补",
    "建",
    "转",
    "拆",
    "锁",
    "砍",
)

# 受控对象类别(闭集)。只在已判定祈使句后用于区分「写」与「未分类」。
OBJECT_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trade", ("订单", "挂单", "委托", "成交")),
    ("strategy", ("策略", "腿", "权重", "参数")),
    ("risk", ("风控", "止损", "止盈", "阈值", "杠杆", "保证金", "预算", "资金", "敞口")),
    ("position", ("仓位", "持仓", "多单", "空单")),
    ("execution", ("实盘", "模式", "授权")),
    ("capital", ("全仓", "满仓", "梭哈", "加仓", "减仓", "清仓")),
)

QUANTITY_RE = re.compile(r"\d+\s*(?:股|手|张|倍|成|%)")

# 仅用于拒绝的中句变更谓词: 只有「谓词 + 受控对象」同时出现才拦截, 不参与放行。
_CHANGE_PREDICATE_RE = re.compile(
    r"(改成|改为|换成|切到|调成|调到|调低|调高|下调|上调|设置|设定|调整|删除|移除|"
    r"清掉|清空|撤掉|撤回|平掉|卖掉|卖光|加到|减到|拉到|移到|换到|提高|降低|上移|"
    r"下移|移仓|换仓|加仓|减仓|平仓|开仓|清仓|建仓|做多|做空|买进|卖出|买入|"
    r"减少|增加|合并|作废|停用|下线|去掉|拆掉|拆分|解锁|锁定|转成|切换为|清干净|删掉|"
    r"减(?:一|两|二|三|四|五|几|\d)|加(?:一|两|二|三|四|五|几|\d))"
)

# 变更谓词后接这些词是名词化短语 (调整历史/建仓成本), 不构成动作请求。
NOMINAL_TAILS: tuple[str, ...] = (
    "历史",
    "记录",
    "过程",
    "空间",
    "说明",
    "情况",
    "明细",
    "原因",
    "建议",
    "方法",
    "方式",
    "报告",
    "评估",
    "流程",
    "规则",
    "步骤",
    "介绍",
    "解释",
    "风险",
    "逻辑",
    "意思",
    "含义",
    "概念",
    "定义",
    "原理",
    "条件",
    "时机",
    "成本",
    "价格",
    "费用",
)

# 变更形态: 与受控对象共现即视为动作请求, 不要求具体谓词在表内。
CHANGE_SHAPES: tuple[str, ...] = (
    # 只保留语义无歧义的变更形态; 成/为/到/一下/了 会被「成本/成交/为什么/解释一下」误伤,
    # 这些动词由 _CHANGE_PREDICATE_RE 覆盖。
    "掉",
    "空",
    "满",
    "半",
    "倍",
    "%",
    "下来",
    "上去",
    "起来",
    "至",
    "干净",
    "净",
)

# 属性查询名词: 「对象 + 的 + 属性」是合法只读结构。
ATTRIBUTE_NOUNS: tuple[str, ...] = (
    "持仓",
    "仓位",
    "成本",
    "风险",
    "风控",
    "敞口",
    "杠杆",
    "权重",
    "腿",
    "记录",
    "情况",
    "明细",
    "审批",
    "收益",
    "回撤",
    "夏普",
    "表现",
    "状态",
    "关系",
    "相关性",
    "覆盖",
    "行情",
    "时段",
    "历史",
    "事件",
    "调整历史",
    "改进空间",
    "审批记录",
)

# 属性询问谓词: 出现在句中说明是在问属性值, 不是要求变更。
ATTRIBUTE_PREDICATES: tuple[str, ...] = (
    "是多少",
    "是什么",
    "怎么样",
    "如何",
    "记录",
    "情况",
    "明细",
    "审批",
    "表现",
    "状态",
)

# 作主语的受控对象名词: 它们出现在句首本身不构成读取许可。
SUBJECT_NOUNS: tuple[str, ...] = (
    "策略",
    "仓位",
    "持仓",
    "目标",
    "回测",
    "风控",
    "敞口",
    "杠杆",
    "权重",
    "腿",
    "订单",
    "资金",
)

# 属性读取许可的模板: 「对象 + 的 + 属性」之后只允许属性谓词或疑问尾。
# 中间出现任何其它成分 (减少/合并/作废/下线/停用...) 都不发许可, 由动作检查先拒绝。
_ATTRIBUTE_NOUN_PATTERN = "|".join(
    sorted((re.escape(noun) for noun in ATTRIBUTE_NOUNS), key=len, reverse=True)
)
_ATTRIBUTE_TEMPLATE_RE = re.compile(
    rf"^(?P<subject>.+?)的"
    rf"(?P<attr>(?:{_ATTRIBUTE_NOUN_PATTERN})(?:(?:的)?(?:{_ATTRIBUTE_NOUN_PATTERN}))*)"
    rf"(?P<rest>.*)$"
)
_ATTRIBUTE_TAIL_PREFIXES: tuple[str, ...] = (
    *ATTRIBUTE_PREDICATES,
    "是",
    "多少",
    "有",
    "怎么",
    "如何",
    "怎么样",
    "有哪些",
    "什么意思",
    "呢",
    "吗",
    "高吗",
    "低吗",
    "大吗",
    "小吗",
)


def _attribute_parts(probe: str) -> tuple[str, str, str] | None:
    match = _ATTRIBUTE_TEMPLATE_RE.match(probe)
    if not match:
        return None
    return match.group("subject"), match.group("attr"), match.group("rest")


# 属性问法的完整尾词: 剥掉这些词之后必须什么都不剩, 只命中前缀不算合法。
_ATTRIBUTE_TAIL_WORDS: tuple[str, ...] = tuple(
    sorted(
        {
            *_ATTRIBUTE_TAIL_PREFIXES,
            "条",
            "个",
            "只",
            "笔",
            "张",
            "手",
            "股",
            "几",
            "一",
            "二",
            "两",
            "三",
            "四",
            "五",
            "六",
            "七",
            "八",
            "九",
            "十",
            "的",
            "现",
            "在",
        },
        key=len,
        reverse=True,
    )
)
_ATTRIBUTE_QUESTION_TAIL_RE = re.compile(
    r"^(?:有|是)?(?:多少|多大|多小|多久|几条|几个|几成|几倍|什么|哪个|哪些|哪里|"
    r"怎么样|怎么|如何)(?:了|吗|呢)?$"
    r"|^(?:变化|上涨|下跌|涨|跌|增加|减少)(?:了)?(?:多少|多大|吗|呢)?$"
)
_ATTRIBUTE_COMPOUND_TAIL_RE = re.compile(
    r"^(?:和|与|及)(?:" + _ATTRIBUTE_NOUN_PATTERN + r")+(?:情况|风险|变化|表现|是多少|多少|吗|呢)?$"
)
_ATTRIBUTE_TAIL_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:条|个|只|笔|张|手|股|成|%|倍)?")


def _attribute_tail_ok(rest: str) -> bool:
    """尾部必须是完整属性谓词/疑问尾, 不能是「是/有/多少/有几」开头再接动作。

    1) 尾部出现任何变更形态或变更谓词 -> 非法 (与开头词无关);
    2) 否则逐个剥掉允许的尾词, 剥完必须为空。
    """

    rest = rest.strip(" ,.!?")
    if not rest:
        return True
    # 纯疑问/变化问法: 「有多大 / 变化了多少 / 上涨了多少 / 和仓位情况」
    if _ATTRIBUTE_QUESTION_TAIL_RE.match(rest):
        return True
    if _ATTRIBUTE_COMPOUND_TAIL_RE.match(rest):
        return True
    if any(shape in rest for shape in CHANGE_SHAPES):
        return False
    if _CHANGE_PREDICATE_RE.search(rest):
        return False
    remaining = rest
    while remaining:
        for word in _ATTRIBUTE_TAIL_WORDS:
            if remaining.startswith(word):
                remaining = remaining[len(word) :]
                break
        else:
            match = _ATTRIBUTE_TAIL_NUMBER_RE.match(remaining)
            if match:
                remaining = remaining[match.end() :]
            else:
                return False
    return True


# 列举式只读句的句首锚点: 「列出当前策略」是查询, 不是指令。
LISTING_PREFIXES: tuple[str, ...] = ("列出", "查看", "查一下", "查询", "显示", "看看")
# 句首读动词: 提问/求证框架, 不是指令 (只作用于句首, 不放行句中动作)。
READ_LEAD_VERBS: tuple[str, ...] = (
    "强调",
    "假设",
    "解释",
    "说明",
    "介绍",
    "分析",
    "评估",
    "对比",
    "列出",
    "查看",
    "查询",
    "显示",
    "看看",
    "解读",
)

# 句首变更谓词: 「修改/调整/设置/更改 + 策略 1 的权重」不能被属性模板当成只读。
LEADING_CHANGE_PREDICATES: tuple[str, ...] = (
    "修改",
    "调整",
    "设置",
    "设定",
    "更改",
    "更新",
    "改掉",
    "换掉",
    "替换",
    "删除",
    "删掉",
    "移除",
    "新增",
    "添加",
    "增加",
    "减少",
    "降低",
    "提高",
    "下调",
    "上调",
    "撤销",
    "取消",
    "审批",
    "批准",
    "启动",
    "停止",
    "开启",
    "关闭",
    "合并",
    "作废",
    "停用",
    "下线",
    "清空",
    "清掉",
    "减掉",
    "去掉",
    "拆分",
    "拆掉",
    "解锁",
    "锁定",
)

_QUESTION_CONTINUATION_RE = re.compile(
    r"^(?:在|于|成|为|是)?(?:哪个|什么|多少|多大|多久|几|怎样|怎么|如何|为什么|"
    r"吗|呢|哪里|哪儿|情况|风险|会不会|是否|没|了(?:多少|多大|几|吗|呢))"
)


# 询问方法/原因的句首锚点: 「如何把仓位清掉」是在问做法, 不是要求执行。
METHOD_QUESTION_PREFIXES: tuple[str, ...] = ("如何", "怎么", "怎样", "为什么", "为何")

# 许可判定前剥掉的叙述性包装, 让关键词落在句首/句末锚点上。
LICENSE_HEAD_WRAPPERS: tuple[str, ...] = (
    "强调",
    "假设",
    "解读",
    "解释",
    "分析",
    "说明",
    "介绍",
    "评估",
    "总结",
    "看看",
    "说一下",
    "讲一下",
    "列出",
    "查一下",
    "查询",
)
LICENSE_FILLER_PREFIXES: tuple[str, ...] = (
    "我",
    "现在",
    "当前",
    "目前",
    "今天",
    "最近",
    "这个",
)
LICENSE_SUFFIXES: tuple[str, ...] = (
    "是多少",
    "是什么",
    "高吗",
    "低吗",
    "大吗",
    "小吗",
    "多少",
    "怎么样",
    "怎么办",
    "如何",
    "怎么样呢",
    "呢",
    "吗",
)

# 正向读取许可: 只有命中这些模式的问题才会读域数据。
READ_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (INTENT_RELATIONS, (r"关系", r"相关", r"关联", r"correlation", r"relation")),
    (INTENT_BACKTEST, (r"回测", r"backtest", r"回撤", r"夏普", r"sortino", r"收益", r"表现")),
    (INTENT_STRATEGY, (r"策略", r"strategy", r"权重", r"腿")),
    (
        INTENT_RISK,
        (
            r"风控",
            r"风险",
            r"敞口",
            r"集中度",
            r"止损",
            r"止盈",
            r"杠杆",
            r"阈值",
            r"risk",
            r"leverage",
        ),
    ),
    (
        INTENT_POSITIONS,
        (
            r"持仓",
            r"仓位",
            r"position",
            r"盈亏",
            r"多单",
            r"空单",
            r"成本",
            r"均价",
            r"浮盈",
            r"浮亏",
            r"成交",
            r"订单",
            r"挂单",
            r"委托",
        ),
    ),
    (INTENT_MARKET, (r"行情", r"市场", r"时段", r"覆盖", r"market", r"session", r"休市")),
)

_ID_PATTERNS: dict[str, tuple[str, ...]] = {
    INTENT_RELATIONS: (r"(?:目标|target)\s*#?(\d+)", r"#(\d+)"),
    INTENT_STRATEGY: (r"(?:策略|strategy)\s*#?(\d+)", r"#(\d+)"),
    INTENT_BACKTEST: (r"(?:回测|backtest|run)\s*#?(\d+)", r"#(\d+)"),
    INTENT_RISK: (r"(?:策略|strategy)\s*#?(\d+)", r"#(\d+)"),
}

# 句读切分: 正文 + 终止符, 终止符保留下来用于判定问号。
# 终止符: 中文逗号/句号/分号/顿号/感叹号/问号, 英文逗号句号感叹号问号, 换行。
_SENTENCE_RE = re.compile(
    r"([^\uff0c\u3002\uff1b\u3001,.\uff01\uff1f!?\n]+)"
    r"([\uff0c\u3002\uff1b\u3001,.\uff01\uff1f!?\n]?)"
)
_WHITESPACE_RE = re.compile(r"[\s\u200b]+")

_QUESTION = "question"
_IMPERATIVE = "imperative"
_UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class Decision:
    """`assess()` 的结果: 是否可作答、只读意图、拒答原因与命中的类别。"""

    answerable: bool
    intent: str | None
    refusal: str | None
    matched: str | None


def normalize_question(question: str) -> str:
    """去掉全部空白与零宽字符并统一小写, 便于实体 id 等纯文本匹配。"""

    return _WHITESPACE_RE.sub("", question or "").lower()


def assess(question: str) -> Decision:
    """判定顺序: 动作安全检查 → 正向读取许可 → 域端口调用(由调用方负责)。"""

    sentences = _sentences(question)
    if not sentences:
        return Decision(False, None, REFUSAL_UNROUTED, None)

    imperatives: list[str | None] = []
    kinds: list[tuple[str, str, str]] = []
    for body, terminator in sentences:
        kind, marker = _kind_of(body, terminator)
        kinds.append((body, kind, marker))
        if kind == _IMPERATIVE:
            imperatives.append(marker)

    if imperatives:
        matched = next((marker for marker in imperatives if marker), None)
        if matched is not None:
            return Decision(False, None, REFUSAL_WRITE, matched)
        return Decision(False, None, REFUSAL_IMPERATIVE, None)

    if any(kind == _UNCERTAIN for _body, kind, _marker in kinds):
        return Decision(False, None, REFUSAL_UNROUTED, None)

    for body, _kind, _marker in kinds:
        decision = _license(body)
        if decision is not None:
            return decision
    return Decision(False, None, REFUSAL_UNLICENSED, None)


def extract_entity_id(question: str, intent: str) -> int | None:
    for pattern in _ID_PATTERNS.get(intent, ()):
        match = re.search(pattern, question)
        if match:
            return int(match.group(1))
    return None


def _sentences(text: str) -> list[tuple[str, str]]:
    # 连词也切句: 「解释一下然后把策略改成做空」的两个分句必须分别判定。
    normalized = re.sub(r"(然后|并且|顺便|同时|接着)", ",", text or "")
    return [
        (match.group(1).strip(), match.group(2))
        for match in _SENTENCE_RE.finditer(normalized)
        if match.group(1).strip()
    ]


def _kind_of(body: str, terminator: str) -> tuple[str, str | None]:
    """句子类型: 先排除「询问方法」, 再跑动作检查, 最后才看问号/疑问词。

    「把策略 1 改成做空？」「能帮我把仓位清掉吗」首先是指令, 不能因为带问号就跳过动作检查;
    只有「如何把仓位清掉」这类询问做法的句子才进入许可侧。
    """

    probe = _strip_politeness(body)
    # 只有「如何/怎么/怎样」这类询问做法的句子可以先离开动作检查;
    # 「为什么」不算: 「为什么止损改到 95」仍包含变更动作, 宁可误拒。
    if probe.startswith(METHOD_QUESTION_PREFIXES):
        return _QUESTION, None
    # 动作检查必须先于一切「友好提前返回」: 只要句子里有动作请求,
    # 无论是否带问号、是否有「对象 + 的 + 属性」结构, 都不得被判成只读。
    marker = _imperative_marker(body)
    if marker is not None:
        return _IMPERATIVE, marker
    # 「成本是多少/是什么/什么意思」是定义/度量问句, 在动作检查为否之后才分类。
    if probe.endswith(
        ("是多少", "是什么", "多少钱", "什么意思", "的区别", "高吗", "低吗", "大吗", "小吗")
    ):
        return _QUESTION, None
    if probe.startswith(READ_LEAD_VERBS) and not (
        ("把" in probe or "将" in probe) and "如何" not in probe and "怎么" not in probe
    ):
        return _QUESTION, None
    if re.search(
        r"(?:在|于|是)?(?:哪个|什么|多少|多大|多久|几|怎样|怎么|如何|为什么|吗|呢)",
        probe,
    ):
        return _QUESTION, None
    if probe.startswith(LISTING_PREFIXES):
        return _QUESTION, None
    if _has_attribute_structure(probe) or probe.startswith(QUESTION_PREFIXES):
        return _QUESTION, None
    if _is_question(body, terminator):
        return _QUESTION, None
    return _UNCERTAIN, None


def _strip_politeness(body: str) -> str:
    for prefix in POLITENESS_PREFIXES:
        if body.startswith(prefix) and len(body) > len(prefix):
            return body[len(prefix) :]
    return body


def _is_question(body: str, terminator: str) -> bool:
    probe = _strip_politeness(body)
    if terminator in QUESTION_TERMINATORS:
        return True
    if probe.startswith(QUESTION_PREFIXES):
        return True
    return probe.endswith(QUESTION_SUFFIXES)


_ATTRIBUTE_QUESTION_RE = re.compile(r"^(什么是|啥是|何为|解释一下|说明一下|介绍一下|分析一下)")
_ATTRIBUTE_QUESTION_SUFFIXES = (
    "是多少",
    "是什么",
    "多少钱",
    "什么意思",
    "高吗",
    "低吗",
    "大吗",
    "小吗",
)


def _is_definition_or_attribute_question(probe: str) -> bool:
    return bool(_ATTRIBUTE_QUESTION_RE.match(probe)) or probe.endswith(_ATTRIBUTE_QUESTION_SUFFIXES)


def _is_question_frame(probe: str) -> bool:
    tail_marks = (
        "吗",
        "呢",
        "多少",
        "多大",
        "多久",
        "几个",
        "哪个",
        "什么",
        "怎样",
        "怎么",
        "如何",
        "为什么",
        "是否",
    )
    if probe.endswith(tail_marks):
        return True
    if "有多大" in probe or "情况" in probe:
        return True
    return bool(re.search(r"(?:哪个|什么|多少|多大|几点|哪儿|哪里)", probe))


def _has_change_with_target(probe: str) -> bool:
    """变更 = 变更形态 ∪ 变更谓词, 不能只认闭集谓词。"""

    if any(shape in probe for shape in CHANGE_SHAPES):
        return True
    for match in _CHANGE_PREDICATE_RE.finditer(probe):
        rest = probe[match.end() :]
        if rest and not _QUESTION_CONTINUATION_RE.match(rest):
            return True
    return False


def _imperative_marker(body: str) -> str | None:
    """祈使句判定: 所有变更判定都先于「读动词/定义式」豁免。

    顺序不可交换: 处置前缀 -> 句首变更谓词 -> 属性尾段 -> 定义式豁免 ->
    中句变更谓词 -> 动作词根 -> 疑问框架 -> 变更形态 -> 读动词豁免。
    """

    probe = _strip_politeness(body)
    if not probe:
        return None
    if probe.startswith(IMPERATIVE_PREFIXES):
        return _object_class(body) or ""
    leading = next((verb for verb in LEADING_CHANGE_PREDICATES if probe.startswith(verb)), None)
    if leading is not None:
        rest = probe[len(leading) :]
        if not rest.startswith(NOMINAL_TAILS) and not _QUESTION_CONTINUATION_RE.match(rest):
            return _object_class(body) or ""
    parts = _attribute_parts(probe)
    if parts is not None and not _attribute_tail_ok(parts[2]):
        # 「对象 + 的 + 属性 + 其它成分」借属性结构夹带动作, 先于豁免拒绝。
        return _object_class(body) or ""
    # 定义式豁免只在这里: 属性尾段已经检查过, 句中夹带的动作不会走到这。
    if _is_definition_or_attribute_question(probe):
        return None
    for match in _CHANGE_PREDICATE_RE.finditer(probe):
        rest = probe[match.end() :]
        if rest.startswith(NOMINAL_TAILS) or _QUESTION_CONTINUATION_RE.match(rest):
            continue
        if _object_class(body) is not None:
            return _object_class(body) or ""
    if probe[0] in ACTION_ROOTS:
        return _object_class(body) or ""
    if _is_question_frame(probe) and not _has_change_with_target(probe):
        return None
    if _object_class(body) is not None and any(shape in probe for shape in CHANGE_SHAPES):
        return _object_class(body) or ""
    # 最后的读动词豁免: 走到这里说明没有任何变更谓词/形态/尾段动作。
    if probe.startswith(READ_LEAD_VERBS):
        return None
    return None


def _object_class(body: str) -> str | None:
    """取「最后一个」受控对象: 「把策略 1 的持仓改成空头」被改的是持仓而不是策略。"""

    best: tuple[int, str] | None = None
    for name, keywords in OBJECT_CLASSES:
        for keyword in keywords:
            index = body.rfind(keyword)
            if index >= 0 and (best is None or index > best[0]):
                best = (index, name)
    if best is not None:
        return best[1]
    if QUANTITY_RE.search(body):
        return "quantity"
    return None


def _strip_license_wrappers(body: str) -> str:
    probe = _strip_politeness(body)
    # 反复剥包装: 「列出当前策略」要同时去掉「列出」和「当前」。
    while True:
        for prefix in LICENSE_HEAD_WRAPPERS + LICENSE_FILLER_PREFIXES:
            if probe.startswith(prefix) and len(probe) > len(prefix):
                probe = probe[len(prefix) :]
                break
        else:
            break
    for suffix in LICENSE_SUFFIXES:
        if probe.endswith(suffix) and len(probe) > len(suffix):
            probe = probe[: -len(suffix)]
            break
    return probe.lstrip("的").strip(" ,.!?")


def _has_attribute_structure(probe: str) -> bool:
    """只认完整模板: 属性谓词不能靠全句包含来判问句。"""

    parts = _attribute_parts(probe)
    return parts is not None and _attribute_tail_ok(parts[2])


def _attribute_anchor(anchored: str, pattern: str) -> bool:
    """「的 + 属性」结构里关键词落在属性位置, 才算读取许可。"""

    if "的" not in anchored:
        return False
    tail = anchored.rsplit("的", 1)[1]
    return bool(re.search(pattern, tail, re.IGNORECASE))


def _license(body: str) -> Decision | None:
    """正向许可: 关键词必须是句首或句末锚点, 不做全句包含匹配。

    这是 Planner v2 的 MUST: 子串包含只能用于拒绝, 不能作为放行条件。
    """

    probe = _strip_politeness(body)
    if probe.startswith(DEFINITION_PREFIXES) or probe.endswith(DEFINITION_SUFFIXES):
        term = glossary.resolve_term(probe)
        if term is None:
            return Decision(False, None, REFUSAL_CONCEPT_UNKNOWN, None)
        return Decision(True, INTENT_CONCEPT, None, term)
    anchored = _strip_license_wrappers(body)
    if probe.startswith(LISTING_PREFIXES) or (
        probe.startswith(READ_LEAD_VERBS) and not _has_change_with_target(probe)
    ):
        for intent, patterns in READ_PATTERNS:
            for pattern in patterns:
                if re.match(pattern, anchored, re.IGNORECASE) or re.search(
                    f"(?:{pattern})$", anchored, re.IGNORECASE
                ):
                    return Decision(True, intent, None, pattern)
        return None
    attribute_question = _has_attribute_structure(probe)
    parts = _attribute_parts(anchored)
    if parts is not None and _attribute_tail_ok(parts[2]):
        for haystack in (parts[1] + parts[2], parts[0] + parts[1] + parts[2]):
            for intent, patterns in READ_PATTERNS:
                for pattern in patterns:
                    if re.search(pattern, haystack, re.IGNORECASE):
                        return Decision(True, intent, None, pattern)
    tail_question = anchored.endswith(
        ("有哪些", "是多少", "是什么", "怎么样", "怎样", "如何", "多少", "吗", "呢")
    )
    for intent, patterns in READ_PATTERNS:
        for pattern in patterns:
            at_start = bool(re.match(pattern, anchored, re.IGNORECASE))
            at_end = bool(re.search(f"(?:{pattern})$", anchored, re.IGNORECASE))
            if at_end:
                return Decision(True, intent, None, pattern)
            if at_start and (
                tail_question or anchored[:1] not in tuple(noun[0] for noun in SUBJECT_NOUNS)
            ):
                return Decision(True, intent, None, pattern)
            if at_start and attribute_question and _attribute_anchor(anchored, pattern):
                return Decision(True, intent, None, pattern)
    if _is_question_frame(probe):
        for intent, patterns in READ_PATTERNS:
            for pattern in patterns:
                if re.match(pattern, anchored, re.IGNORECASE) or re.search(
                    f"(?:{pattern})$", anchored, re.IGNORECASE
                ):
                    return Decision(True, intent, None, pattern)
    return None


__all__ = [
    "INTENT_BACKTEST",
    "INTENT_CONCEPT",
    "INTENT_MARKET",
    "INTENT_POSITIONS",
    "INTENT_RELATIONS",
    "INTENT_RISK",
    "INTENT_STRATEGY",
    "READ_PATTERNS",
    "REFUSAL_MESSAGES",
    "Decision",
    "assess",
    "extract_entity_id",
    "normalize_question",
]
