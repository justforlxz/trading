"""健康检查契约：成功路径的固定字段集合，以及未注册路径的 404。"""

from fastapi.testclient import TestClient

from app import __version__


def test_health_reports_process_identity(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "env": "dev"}
    # 错误路径：未注册的路径不会被健康检查的宽松匹配吞掉。
    assert client.get("/api/healthz").status_code == 404
