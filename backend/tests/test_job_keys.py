"""`job_key` 幂等约定的单元测试。"""

import pytest

from app.jobs.keys import canonical_job_key, canonical_payload


def test_key_is_stable_across_dict_ordering() -> None:
    first = canonical_job_key("ingest_candles", {"inst_id": "AAPL-USDT-SWAP", "bar": "1h"})
    second = canonical_job_key("ingest_candles", {"bar": "1h", "inst_id": "AAPL-USDT-SWAP"})

    assert first == second
    assert len(first) == 64


def test_key_changes_with_payload_or_job_name() -> None:
    base = canonical_job_key("scan_opportunities", {"as_of": "2026-11-06T00:00:00Z"})

    assert canonical_job_key("scan_opportunities", {"as_of": "2026-11-07T00:00:00Z"}) != base
    assert canonical_job_key("ingest_candles", {"as_of": "2026-11-06T00:00:00Z"}) != base


def test_empty_payload_and_none_are_the_same() -> None:
    assert canonical_job_key("sync_instruments") == canonical_job_key("sync_instruments", {})
    assert canonical_payload(None) == "{}"


def test_empty_job_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_job_key("")
