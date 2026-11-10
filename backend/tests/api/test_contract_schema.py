"""契约门禁：应用真实路由、导出产物、响应 example 三者必须一致。

三条独立断言，各自能单独变红：

1. 提交进仓库的 `contracts/openapi.json` 与当前代码导出结果逐字节相同（防漂移）。
2. 每个带响应模型的路由，其模型都带 example，且 example 能通过该模型的校验。
3. 七个业务域都至少被契约覆盖一条路径（防契约被悄悄删空）。

第 2 条是「给 schema 加必填字段但不更新 example」的反例门禁：example 少了必填
字段时 `model_validate` 直接抛 `ValidationError`，测试变红。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.api.schemas import WatchlistResponse
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = BACKEND_ROOT / "contracts" / "openapi.json"

# 响应组件名 → 模型：契约模型只从这两个模块发布（业务域门面 + 健康检查）。
_MODEL_SOURCES = ("app.api.schemas", "app.api.health")

# 七个业务域的路径前缀（不合法即契约缺域）。
DOMAIN_PREFIXES = (
    "/api/watchlist",
    "/api/indicators",
    "/api/strategy-instances",
    "/api/backtests",
    "/api/trades",
    "/api/settings",
    "/api/overview",
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


def test_contract_covers_all_seven_domains() -> None:
    """契约必须真的覆盖七个域，而不是只剩健康检查。"""

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
