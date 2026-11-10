"""令牌桶：容量、匀速补充与等待时长都要可确定性断言。"""

from __future__ import annotations

import pytest

from app.exchange.okx.ratelimit import TokenBucket


class _Clock:
    """可控时钟：只有测试显式推进时才前进。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _bucket(capacity: int, refill: float) -> tuple[TokenBucket, _Clock, list[float]]:
    clock = _Clock()
    sleeps: list[float] = []
    bucket = TokenBucket(capacity, refill, clock=clock, sleep=sleeps.append)
    return bucket, clock, sleeps


@pytest.mark.parametrize(("capacity", "refill"), [(0, 1.0), (-1, 1.0), (1, 0.0), (1, -2.0)])
def test_invalid_construction_raises(capacity: int, refill: float) -> None:
    with pytest.raises(ValueError):
        TokenBucket(capacity, refill)


def test_capacity_is_exposed() -> None:
    bucket, _, _ = _bucket(20, 10.0)
    assert bucket.capacity == 20.0


def test_burst_up_to_capacity_does_not_sleep() -> None:
    bucket, _, sleeps = _bucket(2, 1.0)

    bucket.acquire()
    bucket.acquire()

    assert sleeps == []


def test_exhausted_bucket_waits_for_one_token() -> None:
    bucket, _, sleeps = _bucket(2, 0.5)

    bucket.acquire()
    bucket.acquire()
    bucket.acquire()

    assert sleeps == [2.0]


def test_repeated_exhaustion_waits_each_time() -> None:
    bucket, _, sleeps = _bucket(1, 4.0)

    bucket.acquire()
    bucket.acquire()
    bucket.acquire()

    assert sleeps == [0.25, 0.25]


def test_partial_refill_waits_only_for_the_remainder() -> None:
    bucket, clock, sleeps = _bucket(1, 1.0)
    bucket.acquire()

    clock.now = 0.4
    bucket.acquire()

    assert sleeps == [pytest.approx(0.6)]


def test_full_refill_does_not_wait() -> None:
    bucket, clock, sleeps = _bucket(1, 1.0)
    bucket.acquire()

    clock.now = 5.0
    bucket.acquire()

    assert sleeps == []


def test_refill_is_capped_at_capacity() -> None:
    bucket, clock, sleeps = _bucket(2, 1.0)
    bucket.acquire()
    bucket.acquire()

    clock.now = 100.0
    bucket.acquire()
    bucket.acquire()
    bucket.acquire()

    assert sleeps == [1.0]


@pytest.mark.parametrize("tokens", [0, -1, 3])
def test_out_of_range_token_count_raises(tokens: int) -> None:
    bucket, _, _ = _bucket(2, 1.0)

    with pytest.raises(ValueError):
        bucket.acquire(tokens)
