"""OKX 私有接口签名：HMAC-SHA256 → Base64，以及上游要求的请求头。

上游的签名串是四段直接拼接：`timestamp + method + requestPath + body`，中间没有
分隔符。`requestPath` **必须带查询串**，`body` **必须与实际发出的字节完全一致**，
因此本模块只做纯计算：调用方把最终要发出去的字符串传进来，签名和发送就不可能
各算一套。

时间戳格式是 ISO-8601 UTC、毫秒精度、`Z` 结尾（`2026-11-10T04:26:00.123Z`）。
毫秒是**截断**而不是四舍五入：把微秒进位会得到一个比真实时刻晚的时间戳，上游
对时间差有上限，截断永远落在上限之内。

WebSocket 登录用的是同一套 HMAC，只是签名串换成
`epoch 秒 + "GET" + "/users/self/verify"`，见 `ws_login_signature`。

`require_credentials` 也在这里：签名需要的三件凭据（Key / Secret / 口令）缺一件都
算不上「配好了」，REST 与 WebSocket 共用这一处判断。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime

from app.config import Settings
from app.core import ValidationError

__all__ = [
    "iso_timestamp",
    "require_credentials",
    "sign",
    "sign_headers",
    "ws_login_signature",
]

#: 上游时间戳格式：秒级部分用 `strftime`，毫秒部分单独拼，避免对微秒串做切片算术。
_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%S"
_MICROSECONDS_PER_MILLISECOND = 1000
#: WebSocket 登录签名的固定占位路径。
WS_LOGIN_PATH = "/users/self/verify"
#: 模拟盘请求头：值固定为 "1"，实盘不带这个头。
SIMULATED_TRADING_HEADER = "x-simulated-trading"


def require_credentials(settings: Settings) -> None:
    """私有接口的三件凭据必须齐全；缺哪个就报哪个，不发注定 401 的请求。"""

    missing = [
        name
        for name, value in (
            ("OKX_API_KEY", settings.okx_api_key),
            ("OKX_SECRET_KEY", settings.okx_secret_key),
            ("OKX_PASSPHRASE", settings.okx_passphrase),
        )
        if not value.strip()
    ]
    if missing:
        raise ValidationError(f"缺少私有接口凭据:{', '.join(missing)}")


def iso_timestamp(moment: datetime) -> str:
    """带时区的时刻 → 上游时间戳（UTC、毫秒精度、`Z` 结尾）。"""

    if moment.tzinfo is None:
        raise ValidationError("签名时间戳必须带时区")
    stamp = moment.astimezone(UTC)
    milliseconds = stamp.microsecond // _MICROSECONDS_PER_MILLISECOND
    return f"{stamp.strftime(_SECONDS_FORMAT)}.{milliseconds:03d}Z"


def sign(
    secret: str,
    *,
    timestamp: str,
    method: str,
    request_path: str,
    body: str = "",
) -> str:
    """计算签名：`Base64(HMAC-SHA256(secret, timestamp + method + path + body))`。

    `method` 统一大写：上游只认大写，小写会被判签名错误。
    """

    message = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def sign_headers(
    *,
    api_key: str,
    secret: str,
    passphrase: str,
    timestamp: str,
    method: str,
    request_path: str,
    body: str = "",
    demo: bool = False,
) -> dict[str, str]:
    """构造私有接口的全部请求头。

    模拟盘与实盘走同一个域名，靠 `x-simulated-trading: 1` 区分；实盘不发送这个头，
    而不是发一个 `0`——上游对未知取值的处理不属于本层能替它决定的事。
    """

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign(
            secret,
            timestamp=timestamp,
            method=method,
            request_path=request_path,
            body=body,
        ),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    if demo:
        headers[SIMULATED_TRADING_HEADER] = "1"
    return headers


def ws_login_signature(secret: str, *, epoch_seconds: int) -> str:
    """WebSocket 登录签名：签名串是 `epoch 秒 + GET + /users/self/verify`。"""

    return sign(
        secret,
        timestamp=str(epoch_seconds),
        method="GET",
        request_path=WS_LOGIN_PATH,
    )
