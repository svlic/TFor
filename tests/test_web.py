import json

import pytest
from fastapi.testclient import TestClient

from tfor.main import app, parse_filters


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

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["database"]["ok"] is True
        assert health.json()["runtime"]["deferred_worker_running"] == 1


def test_filter_parser_rejects_invalid_regex() -> None:
    raw = json.dumps(
        [{"kind": "blacklist", "field": "text", "match_mode": "regex", "values": "[invalid"}]
    )

    with pytest.raises(ValueError, match="正则表达式无效"):
        parse_filters(raw)


def test_filter_parser_rejects_unknown_step_options() -> None:
    raw = json.dumps(
        [{"kind": "unknown", "field": "text", "match_mode": "contains", "values": "value"}]
    )

    with pytest.raises(ValueError, match="过滤类型无效"):
        parse_filters(raw)
