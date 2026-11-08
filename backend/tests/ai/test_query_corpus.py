"""P4-05: 问答语料是唯一事实源, 逐条按「允许结果集合」断言。

`data/query_cases.json` 同时被 `scripts/e2e/p4_smoke.sh` 读取, 避免测试与冒烟各维护
一份清单。断言只认三类结果:

- `answered`: 200 且 `answerable=true`;
- `forbidden`: 403 `ai_write_forbidden`, 或 200 且 `answerable=false`;
- `unlicensed`: 200 且 `answerable=false`, `citations=[]`。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ai.conftest import seed_full_backtest

CASES_PATH = Path(__file__).parent / "data" / "query_cases.json"
CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
ALLOWED_RESULTS = {"answered", "unlicensed", "forbidden"}


@pytest.mark.parametrize("case", CASES, ids=[case["text"] for case in CASES])
async def test_query_corpus_matches_allowed_results(
    client: AsyncClient, session: AsyncSession, configure_ai, case: dict[str, Any]
) -> None:
    configure_ai()
    if case.get("seed") == "backtest":
        # 语料里引用实体 id 的只读问法需要先播种; 播种在断言窗口之外。
        await seed_full_backtest(session)
    expect = set(case["expect"])
    assert expect <= ALLOWED_RESULTS, case

    response = await client.post("/api/v1/ai/query", json={"question": case["text"]})

    if response.status_code == 403:
        assert "forbidden" in expect, (case["text"], response.text)
        error = response.json()["error"]
        assert error["code"] == "ai_write_forbidden"
        assert error["details"]["refusal"]["matched_object_class"]
        return

    assert response.status_code == 200, (case["text"], response.text)
    payload = response.json()
    assert payload["read_only"] is True

    if payload["answerable"]:
        assert "answered" in expect, (case["text"], payload)
        assert payload["answer"]
        if case.get("intent") == "concept":
            # 概念类事实只能来自静态术语表, 不能是域数据。
            glossary_citations = [
                item for item in payload["citations"] if item["type"] == "glossary"
            ]
            assert glossary_citations, payload
            term = glossary_citations[0]["term"]
            assert term and glossary_citations[0]["definition"]
            assert glossary_citations[0]["source"] == f"glossary#{term}"
        if case.get("intent"):
            assert payload["intent"] == case["intent"], (case["text"], payload)
        return

    # 拒答: 403 或未许可都应落在允许集合里, 且不得带任何域数据。
    assert "unlicensed" in expect or "forbidden" in expect, (case["text"], payload)
    assert payload["citations"] == []
    assert payload["reason"]
    assert "missing" not in payload
    assert "legs" not in payload
    assert "draft_only" not in payload
