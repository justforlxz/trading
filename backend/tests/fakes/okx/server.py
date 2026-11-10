"""假 OKX 的独立进程入口。

    python -m tests.fakes.okx.server --port 18080
    python -m tests.fakes.okx.server --port 18080 --rate-limited
    python -m tests.fakes.okx.server --port 18080 --slow 1.5

同一个模块也提供 `start_server()`：在后台线程里监听真实端口，
给只支持同步 HTTP 的适配器（`httpx.BaseTransport`）连接用。
"""

from __future__ import annotations

import argparse
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI

from tests.fakes.okx.app import create_app
from tests.fakes.okx.scenarios import Scenarios
from tests.fakes.okx.store import OkxStore

STARTUP_TIMEOUT_SECONDS = 10.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0


@dataclass
class FakeOkxServer:
    """线程内运行的假 OKX。"""

    host: str
    port: int
    app: FastAPI
    store: OkxStore
    scenarios: Scenarios
    _server: uvicorn.Server = field(repr=False)
    _thread: threading.Thread = field(repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=SHUTDOWN_TIMEOUT_SECONDS)

    def __enter__(self) -> FakeOkxServer:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()


def start_server(
    *,
    host: str = "127.0.0.1",
    port: int = 18080,
    scenarios: Scenarios | None = None,
) -> FakeOkxServer:
    """在后台线程启动假 OKX；`port=0` 由系统分配空闲端口。"""

    active = scenarios if scenarios is not None else Scenarios()
    store = OkxStore()
    app = create_app(store=store, scenarios=active)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="fake-okx", daemon=True)
    thread.start()
    _wait_until_started(server, thread)
    return FakeOkxServer(
        host=host,
        port=_bound_port(server, fallback=port),
        app=app,
        store=store,
        scenarios=active,
        _server=server,
        _thread=thread,
    )


def _wait_until_started(server: uvicorn.Server, thread: threading.Thread) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("假 OKX 启动失败:uvicorn 线程已退出")
        if time.monotonic() > deadline:
            server.should_exit = True
            raise TimeoutError("假 OKX 启动超时")
        time.sleep(0.005)


def _bound_port(server: uvicorn.Server, *, fallback: int) -> int:
    for bound in server.servers:
        for sock in bound.sockets or []:
            return int(sock.getsockname()[1])
    return fallback


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.fakes.okx.server",
        description="启动假 OKX 行情服务 (测试专用, 不连真实上游)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--rate-limited", action="store_true", help="所有响应返回 HTTP 429 / code 50011"
    )
    parser.add_argument(
        "--upstream-error", action="store_true", help="所有响应返回 HTTP 500 / code 50001"
    )
    parser.add_argument(
        "--slow", type=float, default=0.0, metavar="SECONDS", help="每个响应额外延迟的秒数"
    )
    args = parser.parse_args(argv)

    scenarios = Scenarios()
    if args.rate_limited:
        scenarios.activate("rate_limited")
    if args.upstream_error:
        scenarios.activate("upstream_error")
    if args.slow:
        scenarios.slow(args.slow)

    uvicorn.run(create_app(scenarios=scenarios), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
