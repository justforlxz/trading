"""机会发现端点：列表、详情与状态流转的 HTTP 契约与错误路径。

端点只读已落库的机会，所以用例先用服务入口把一次检测跑进库里，再对着真实响应断言
形状与错误码。分数必须能被契约的十进制正则接受，时间必须是 `Z` 结尾的 UTC。
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from app.opportunity import detect_opportunities
from tests.factories.instruments import make_ref
from tests.opportunity.conftest import AS_OF, seed_daily, seed_instruments

DECIMAL = re.compile(r"^-?\d{1,20}(\.\d{1,12})?$")
UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

ANCHOR_CLOSES = ["100", "120", "100", "120", "100"]
NEIGHBOUR_CLOSES = ["50", "60", "50", "60", "55"]


def _seed_opportunity() -> str:
    """一个锚点与两个邻居的日线，跑一次目标驱动检测，返回落库的机会标识。"""

    seed_instruments(
        make_ref(),
        make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"),
        make_ref(inst_id="XNVDA-USDT", base_ccy="XNVDA"),
    )
    seed_daily("XAAPL-USDT", ANCHOR_CLOSES)
    seed_daily("XMSFT-USDT", NEIGHBOUR_CLOSES)
    seed_daily("XNVDA-USDT", NEIGHBOUR_CLOSES)
    (record,) = detect_opportunities(AS_OF, "1d", anchor_product_key="AAPL")
    return record.opportunity_id


def test_opportunity_list_starts_empty(client: TestClient) -> None:
    response = client.get("/api/opportunities")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_opportunity_list_returns_the_stored_opportunity(client: TestClient) -> None:
    opportunity_id = _seed_opportunity()

    response = client.get("/api/opportunities")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["opportunity_id"] == opportunity_id
    assert item["mode"] == "target"
    assert item["anchor_product_key"] == "AAPL"
    assert item["as_of"] == "2026-11-10T23:00:00Z"
    assert UTC_ZULU.match(item["as_of"])
    assert item["status"] == "new"
    assert DECIMAL.match(item["score"])
    # `evidence` 是判定依据的 JSON 文本，原样透传，不在这里二次解释。
    assert json.loads(item["evidence"])["anchor_product_key"] == "AAPL"
    assert {leg["product_key"] for leg in item["legs"]} == {"MSFT", "NVDA"}
    for leg in item["legs"]:
        assert leg["inst_type"] == "SPOT"
        assert leg["direction"] == "long"
        assert DECIMAL.match(leg["score"])


def test_opportunity_detail_and_unknown_id(client: TestClient) -> None:
    opportunity_id = _seed_opportunity()

    found = client.get(f"/api/opportunities/{opportunity_id}")
    missing = client.get("/api/opportunities/opp_missing")

    assert found.status_code == 200
    assert found.json()["opportunity_id"] == opportunity_id
    assert missing.status_code == 404


def test_opportunity_status_transition(client: TestClient) -> None:
    opportunity_id = _seed_opportunity()

    reviewed = client.patch(f"/api/opportunities/{opportunity_id}", json={"status": "reviewed"})

    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "reviewed"
    (item,) = client.get("/api/opportunities").json()["items"]
    assert item["status"] == "reviewed"


def test_illegal_transition_is_rejected(client: TestClient) -> None:
    """`reviewed` 不能回到 `new`：非法转移由域层拒绝，端点把它翻译成 400。"""

    opportunity_id = _seed_opportunity()
    client.patch(f"/api/opportunities/{opportunity_id}", json={"status": "reviewed"})

    response = client.patch(f"/api/opportunities/{opportunity_id}", json={"status": "new"})

    assert response.status_code == 400
    (item,) = client.get("/api/opportunities").json()["items"]
    assert item["status"] == "reviewed"


def test_unknown_opportunity_status_update_is_404(client: TestClient) -> None:
    response = client.patch("/api/opportunities/opp_missing", json={"status": "reviewed"})

    assert response.status_code == 404


def test_unknown_status_value_is_rejected_by_the_contract(client: TestClient) -> None:
    opportunity_id = _seed_opportunity()

    response = client.patch(f"/api/opportunities/{opportunity_id}", json={"status": "archived"})

    assert response.status_code == 422


def test_opportunity_filters(client: TestClient) -> None:
    opportunity_id = _seed_opportunity()

    by_mode = client.get("/api/opportunities", params={"mode": "target"}).json()
    other_mode = client.get("/api/opportunities", params={"mode": "market"}).json()
    by_anchor = client.get("/api/opportunities", params={"anchor_product_key": "aapl"}).json()
    by_status = client.get("/api/opportunities", params={"status": "new"}).json()
    limited = client.get("/api/opportunities", params={"limit": 1}).json()
    rejected = client.get("/api/opportunities", params={"mode": "everything"})

    assert by_mode["items"][0]["opportunity_id"] == opportunity_id
    assert other_mode == {"items": [], "total": 0}
    assert by_anchor["total"] == 1
    assert by_status["total"] == 1
    assert (len(limited["items"]), limited["total"]) == (1, 1)
    assert rejected.status_code == 422
