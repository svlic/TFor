from fastapi.testclient import TestClient

from tfor.main import app


def test_core_pages_render() -> None:
    with TestClient(app) as client:
        for path, heading in (
            ("/", "运行概览"),
            ("/accounts", "Telegram 账号"),
            ("/rules", "转发规则"),
            ("/logs", "处理日志"),
            ("/settings", "系统设置"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert heading in response.text

        assert client.get("/health").json() == {"status": "ok"}
