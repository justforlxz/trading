"""第三方行情源的公共 HTTP 细节：超时、UA 与「非 200 即上游错误」。

两个实现共用同一份取数逻辑，差别只在地址与解析；这些约定放在一处，不各写一套。
"""

from __future__ import annotations

import httpx

from app.core import UpstreamError

__all__ = ["HTTP_TIMEOUT", "USER_AGENT", "get_text"]

HTTP_TIMEOUT = httpx.Timeout(10.0)
#: Yahoo 与 Stooq 都对本机 Linux Chrome UA 回 429 / 挑战页，Windows 桌面 UA 才 200
#: （实测），因此固定用 Windows 桌面写法。
USER_AGENT = (
    "Mozilla"
    "/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def get_text(url: str, client: httpx.Client | None) -> str:
    """取回上游正文；网络错误与非 200 都转成 `UpstreamError`。"""

    try:
        if client is not None:
            response = client.get(url)
        else:
            with httpx.Client(
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as local:
                response = local.get(url)
    except httpx.HTTPError as exc:
        raise UpstreamError(f"行情上游请求失败: {exc}") from exc
    if response.status_code != 200:
        raise UpstreamError(f"行情上游返回 HTTP {response.status_code}")
    return response.text
