"""私有接口签名：固定输入对拍**手工算出来**的期望值。

期望值是先用 `openssl dgst -sha256 -hmac <secret> -binary | openssl base64 -A` 算好
写死在这里的，不是拿被测实现算一遍再跟它自己比——否则「签名算错了」和「期望值也算错
了」会互相掩盖。

三条用例覆盖三种签名串形态：带查询串的 GET、带请求体的 POST、WebSocket 登录。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core import ValidationError
from app.exchange.okx.sign import iso_timestamp, sign, sign_headers, ws_login_signature

SECRET = "test-secret"
TIMESTAMP = "2026-11-10T04:26:00.123Z"

# 签名串：`2026-11-10T04:26:00.123Z` + `GET` + `/api/v5/account/balance?ccy=USDT`
EXPECTED_GET_SIGN = "TR0L02xvZ7hV2+IQcb+NR6fdL223NCbUzBamE55Lf0E="
# 签名串：`2026-11-10T04:26:00.123Z` + `POST` + `/api/v5/trade/order` + 下面的请求体
POST_BODY = (
    '{"instId":"BTC-USDT-SWAP","side":"buy","ordType":"limit","sz":"1",'
    '"px":"100","tdMode":"cross","posSide":"long","clOrdId":"c-1"}'
)
EXPECTED_POST_SIGN = "FMEXj0YWjdw2LcH4RaED1cEmOK2AKTWLiRr1TMNSPJ4="
# 签名串：`1794284760` + `GET` + `/users/self/verify`
EXPECTED_LOGIN_SIGN = "ow4+nnXrMw6YpGRu6fbT0HdCCnNYv9m3WsiPafss08k="


def test_timestamp_keeps_milliseconds_and_drops_the_rest() -> None:
    """微秒被截断而不是进位：时间戳永远不会比真实时刻更晚。"""

    moment = datetime(2026, 11, 10, 4, 26, 0, 123456, tzinfo=UTC)

    assert iso_timestamp(moment) == TIMESTAMP


def test_timestamp_is_converted_to_utc() -> None:
    """带偏移的时刻先折算到 UTC，`Z` 才名副其实。"""

    moment = datetime(2026, 11, 10, 12, 26, 0, 123000, tzinfo=timezone(timedelta(hours=8)))

    assert iso_timestamp(moment) == TIMESTAMP


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        iso_timestamp(datetime(2026, 11, 10, 4, 26))


def test_get_signature_matches_the_hand_computed_value() -> None:
    assert (
        sign(
            SECRET,
            timestamp=TIMESTAMP,
            method="GET",
            request_path="/api/v5/account/balance?ccy=USDT",
        )
        == EXPECTED_GET_SIGN
    )


def test_post_signature_includes_the_request_body() -> None:
    assert (
        sign(
            SECRET,
            timestamp=TIMESTAMP,
            method="POST",
            request_path="/api/v5/trade/order",
            body=POST_BODY,
        )
        == EXPECTED_POST_SIGN
    )


def test_method_is_upper_cased_before_signing() -> None:
    """上游只认大写方法；传小写也要得到同一个签名，不能悄悄算成另一个。"""

    assert (
        sign(
            SECRET,
            timestamp=TIMESTAMP,
            method="get",
            request_path="/api/v5/account/balance?ccy=USDT",
        )
        == EXPECTED_GET_SIGN
    )


def test_a_different_secret_produces_a_different_signature() -> None:
    assert (
        sign(
            "another-secret",
            timestamp=TIMESTAMP,
            method="GET",
            request_path="/api/v5/account/balance?ccy=USDT",
        )
        != EXPECTED_GET_SIGN
    )


def test_headers_carry_every_field_the_upstream_requires() -> None:
    headers = sign_headers(
        api_key="key-1",
        secret=SECRET,
        passphrase="pass-1",
        timestamp=TIMESTAMP,
        method="GET",
        request_path="/api/v5/account/balance?ccy=USDT",
        demo=True,
    )

    assert headers["OK-ACCESS-KEY"] == "key-1"
    assert headers["OK-ACCESS-SIGN"] == EXPECTED_GET_SIGN
    assert headers["OK-ACCESS-TIMESTAMP"] == TIMESTAMP
    assert headers["OK-ACCESS-PASSPHRASE"] == "pass-1"
    assert headers["x-simulated-trading"] == "1"


def test_live_headers_do_not_claim_to_be_simulated() -> None:
    """实盘不发 `x-simulated-trading`：发一个 0 是把「不声明」当成「声明实盘」。"""

    headers = sign_headers(
        api_key="key-1",
        secret=SECRET,
        passphrase="pass-1",
        timestamp=TIMESTAMP,
        method="GET",
        request_path="/api/v5/account/balance",
        demo=False,
    )

    assert "x-simulated-trading" not in headers


def test_websocket_login_signature_matches_the_hand_computed_value() -> None:
    """WS 登录的签名串是 `epoch 秒 + GET + /users/self/verify`，与 REST 不同。"""

    assert ws_login_signature(SECRET, epoch_seconds=1794284760) == EXPECTED_LOGIN_SIGN
