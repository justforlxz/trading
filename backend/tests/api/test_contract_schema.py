"""契约门禁：应用真实路由、导出产物、响应 example 三者必须一致。

五条独立断言，各自能单独变红：

1. 提交进仓库的 `contracts/openapi.json` 与当前代码导出结果逐字节相同（防漂移）。
2. 每个带响应模型的路由，其模型都带 example，且 example 能通过该模型的校验。
3. 十二个业务域都至少被契约覆盖一条路径（防契约被悄悄删空）。
4. 新增五个域各有一条「最小合法载荷可序列化 + 缺必填字段报错」用例。
5. 契约里的枚举与领域层/决策文档逐字对齐（`AssetType`、`DataSource`、
   `StrategyStatus`）。

第 2 条是「给 schema 加必填字段但不更新 example」的反例门禁：example 少了必填
字段时 `model_validate` 直接抛 `ValidationError`，测试变红。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app.api.schemas import (
    CorrelationMatrixResponse,
    InstrumentRef,
    OpportunityStatusUpdateRequest,
    PortfolioAdjustmentCreateRequest,
    RelationNeighborsResponse,
    StrategyApprovalRequest,
    StrategyInstanceUpdateRequest,
    WatchlistResponse,
)
from app.api.schemas.common import AssetType, DataSource, StrategyStatus
from app.instrument.model import _ASSET_TYPES, UNKNOWN_ASSET_TYPE
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = BACKEND_ROOT / "contracts" / "openapi.json"

# 响应组件名 → 模型：契约模型只从这两个模块发布（业务域门面 + 健康检查）。
_MODEL_SOURCES = ("app.api.schemas", "app.api.health")

# 十二个业务域的路径前缀（不合法即契约缺域）。
DOMAIN_PREFIXES = (
    "/api/watchlist",
    "/api/indicators",
    "/api/strategy-instances",
    "/api/backtests",
    "/api/trades",
    "/api/settings",
    "/api/overview",
    "/api/correlation",
    "/api/market",
    "/api/relations",
    "/api/opportunities",
    "/api/portfolio",
    "/api/approvals",
)


def _rendered_contract() -> str:
    """与 `scripts/export_openapi.py` 完全相同的序列化口径。"""

    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _response_models() -> list[tuple[str, str, type[BaseModel]]]:
    """从导出的契约里取「路径 + 方法 + 响应模型」，模型按组件名回查门面。

    直接用 openapi 文档而不是遍历 `app.routes`：契约文件才是前端消费的东西，
    这样也就同时校验了组件名与门面导出的一致性。
    """

    import importlib

    found: list[tuple[str, str, type[BaseModel]]] = []
    for path, operations in json.loads(_rendered_contract())["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for status, response in operation.get("responses", {}).items():
                if not status.startswith("2"):
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                ref = schema.get("$ref")
                if ref is None:
                    continue  # 204 无响应体
                name = ref.rsplit("/", maxsplit=1)[-1]
                model = next(
                    (
                        candidate
                        for source in _MODEL_SOURCES
                        for candidate in [getattr(importlib.import_module(source), name, None)]
                        if candidate is not None
                    ),
                    None,
                )
                assert isinstance(model, type) and issubclass(model, BaseModel), (
                    f"{path} {method} 的响应组件 `{name}` 未在契约模型模块发布"
                )
                found.append((f"{method.upper()} {path}", name, model))
    return found


def _examples(model: type[BaseModel]) -> list[object]:
    extra = model.model_config.get("json_schema_extra")
    if not isinstance(extra, dict):
        return []
    examples = extra.get("examples")
    assert isinstance(examples, list), f"{model.__name__} 的 examples 必须是列表"
    return examples


def test_committed_contract_matches_application() -> None:
    """契约未漂移: 重新导出后 `git diff --exit-code` 必然为空。"""

    assert CONTRACT_PATH.is_file(), f"缺少契约文件: {CONTRACT_PATH}"
    assert CONTRACT_PATH.read_text(encoding="utf-8") == _rendered_contract(), (
        "contracts/openapi.json 与代码不一致, 请运行 "
        "`python backend/scripts/export_openapi.py` 并提交结果"
    )


def test_every_response_model_has_a_valid_example() -> None:
    """每个响应模型都带 example, 且 example 满足模型自身的必填与格式约束。"""

    problems: list[str] = []
    routes = _response_models()
    assert routes, "没有任何带响应模型的路由, 契约是空的"

    for label, name, model in routes:
        examples = _examples(model)
        if not examples:
            problems.append(f"{label} 的 {name} 没有 example")
            continue
        for index, example in enumerate(examples):
            try:
                model.model_validate(example)
            except ValidationError as exc:
                problems.append(f"{label} 的 {name} example[{index}] 不合法: \n{exc}")
    assert not problems, "\n".join(problems)


def test_contract_covers_all_domains() -> None:
    """契约必须真的覆盖全部业务域，而不是只剩健康检查。"""

    paths = set(json.loads(_rendered_contract())["paths"])
    missing = [prefix for prefix in DOMAIN_PREFIXES if not any(p.startswith(prefix) for p in paths)]
    assert not missing, f"契约缺少业务域: {missing}"


def test_example_missing_required_field_is_rejected() -> None:
    """反例固化：拿掉一个必填字段后，与门禁同一条校验必须报错。"""

    example = _examples(WatchlistResponse)[0]
    assert isinstance(example, dict)
    required = [
        name
        for name, field in WatchlistResponse.model_fields.items()
        if field.is_required() and name in example
    ]
    assert required, "WatchlistResponse 的 example 缺少必填字段, 反例无法构造"
    broken = {key: value for key, value in example.items() if key != required[0]}

    with pytest.raises(ValidationError):
        WatchlistResponse.model_validate(broken)


# 新增五个域各一条最小载荷：只读域没有请求体，用最小的响应载荷；有写接口的域用请求模型。
_DOMAIN_PAYLOADS = (
    (
        "correlation",
        CorrelationMatrixResponse,
        {
            "bar": "1d",
            "window": 60,
            "as_of": "2026-11-10T00:00:00Z",
            "product_keys": ["AAPL"],
            "cells": [],
        },
    ),
    (
        "relations",
        RelationNeighborsResponse,
        {"product_key": "AAPL", "bar": "1d", "window": 60, "items": []},
    ),
    ("opportunity", OpportunityStatusUpdateRequest, {"status": "reviewed"}),
    (
        "portfolio",
        PortfolioAdjustmentCreateRequest,
        {
            "instance_id": "si_0001",
            "requested_by": "lxz",
            "target": {
                "legs": [
                    {
                        "inst_id": "XAAPL-USDT",
                        "inst_type": "SPOT",
                        "direction": "long",
                        "target_weight": "0.25",
                    }
                ],
                "net_exposure": "0.25",
            },
        },
    ),
    ("approval", StrategyApprovalRequest, {"instance_id": "si_0001", "actor": "lxz"}),
)

LIFECYCLE_STAGES = (
    "opportunity_discovery",
    "strategy_generation",
    "pending_review",
    "backtested",
    "validated",
    "paper_trading",
    "live_authorized",
    "live_running",
)

DECISIONS_PATH = BACKEND_ROOT.parent / "docs" / "prd" / "decisions.md"


def _decision_section(text: str, key: str) -> str:
    """截出决策文档里的一节（到下一个二级标题为止），避免对整份文件做子串匹配。"""

    start = text.find(f"## {key} ")
    assert start >= 0, f"decisions.md 缺少 {key} 一节"
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


@pytest.mark.parametrize(
    ("domain", "model", "payload"),
    _DOMAIN_PAYLOADS,
    ids=[case[0] for case in _DOMAIN_PAYLOADS],
)
def test_new_domain_minimal_payload_round_trips(
    domain: str, model: type[BaseModel], payload: dict[str, object]
) -> None:
    """最小合法载荷能序列化成 JSON 文本（不泄漏 Decimal/datetime），少必填字段即报错。"""

    instance = model.model_validate(payload)
    rendered = json.dumps(instance.model_dump(mode="json"))
    assert model.model_validate(json.loads(rendered)) == instance, f"{domain} 的载荷往返不一致"

    required = [
        name
        for name, field in model.model_fields.items()
        if field.is_required() and name in payload
    ]
    assert required, f"{domain} 的最小载荷没有必填字段, 缺字段反例无法构造"
    broken = {key: value for key, value in payload.items() if key != required[0]}

    with pytest.raises(ValidationError):
        model.model_validate(broken)


def test_every_instrument_asset_type_serializes() -> None:
    """`AssetType` 等于 `app.instrument` 的四种落库取值，四种都能原样序列化。

    `commodity_token` 是 AC 指定的反例：它来自真实标的（`XAUT-USDT`），
    契约若比领域层窄，响应构造时就会校验失败。
    """

    domain_values = set(_ASSET_TYPES.values()) | {UNKNOWN_ASSET_TYPE}
    assert set(get_args(AssetType)) == domain_values
    assert "commodity_token" in domain_values

    for asset_type in sorted(domain_values):
        ref = InstrumentRef(
            inst_id="XAUT-USDT",
            inst_type="SPOT",
            product_key="XAUT",
            asset_type=asset_type,
            base_currency="XAUT",
            quote_currency="USDT",
        )
        assert json.loads(ref.model_dump_json())["asset_type"] == asset_type


def test_source_identifier_is_split_by_category() -> None:
    """来源标识已按类别拆分：应用代码里不得再出现只含 `okx` 的字面枚举。"""

    assert set(get_args(DataSource)) == {"okx", "okx_spot", "okx_swap", "us_equity_proxy"}

    offenders = [
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in (BACKEND_ROOT / "app").rglob("*.py")
        if 'Literal["okx"]' in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"来源标识仍被收窄为单一 `okx`: {offenders}"


def test_strategy_status_matches_lifecycle_document() -> None:
    """八阶段生命周期加驳回分支，取值与 `docs/prd/decisions.md` D7 逐字一致。"""

    values = get_args(StrategyStatus)
    assert values[:8] == LIFECYCLE_STAGES, "八个阶段的顺序必须与 PRD §三.5 一致"
    assert values[8:] == ("rejected",), "驳回分支只能有一个额外取值"

    section = _decision_section(DECISIONS_PATH.read_text(encoding="utf-8"), "D7")
    missing = [value for value in values if f"`{value}`" not in section]
    assert not missing, f"decisions.md D7 与枚举不一致, 缺少: {missing}"


def test_lifecycle_can_only_be_advanced_through_approvals() -> None:
    """实例 PATCH 不接受生命周期取值：阶段只能经 `/api/approvals` 的状态机推进。"""

    fields = StrategyInstanceUpdateRequest.model_fields
    assert "status" not in fields, "PATCH 仍能写生命周期, 审批状态机可被绕过"
    assert "enabled" in fields, "启停开关缺失, T3.3 没有可用的显式字段"

    StrategyInstanceUpdateRequest.model_validate({"enabled": False})
    for value in get_args(StrategyStatus):
        with pytest.raises(ValidationError):
            StrategyInstanceUpdateRequest.model_validate({"status": value})


def test_as_of_requires_timezone(client: TestClient) -> None:
    """`as_of` 必须带时区：本地时间不得被当成 UTC（`AGENTS.md` §3）。"""

    params = {"inst_type": "SPOT", "as_of": "2026-11-10T00:00:00"}

    assert client.get("/api/market/overview", params=params).status_code == 422

    params["as_of"] = "2026-11-10T00:00:00Z"
    assert client.get("/api/market/overview", params=params).status_code == 200
