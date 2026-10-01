import json
import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from thursday_contracts.health import ReadinessCheck, ServiceName
from thursday_runtime.auth import ServiceTokenAuth
from thursday_runtime.health import build_health_router
from thursday_runtime.log_setup import JsonLineFormatter
from thursday_runtime.paths import data_root


def app_with_probes(**probes: object) -> TestClient:
    app = FastAPI()
    app.include_router(build_health_router(ServiceName.GATEWAY, "0.1.0", probes))  # type: ignore[arg-type]
    return TestClient(app)


async def ok() -> ReadinessCheck:
    return ReadinessCheck(ok=True)


async def down() -> ReadinessCheck:
    return ReadinessCheck(ok=False, detail="llm endpoint unreachable")


async def broken() -> ReadinessCheck:
    raise RuntimeError("boom")


def test_health_is_up_even_when_not_ready() -> None:
    client = app_with_probes(llm=down)
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["checks"]["llm"] == {"ok": False, "detail": "llm endpoint unreachable"}


def test_ready_when_all_probes_pass() -> None:
    assert app_with_probes(a=ok, b=ok).get("/ready").json()["ready"] is True


def test_raising_probe_reports_not_ready_instead_of_crashing() -> None:
    body = app_with_probes(a=ok, b=broken).get("/ready").json()
    assert body["ready"] is False and body["checks"]["b"]["detail"] == "RuntimeError"


def guarded(token: str) -> TestClient:
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(ServiceTokenAuth(SecretStr(token)))])
    async def x() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic s3cret", "s3cret"])
def test_service_token_rejects_missing_or_wrong(header: str | None) -> None:
    headers = {"Authorization": header} if header else {}
    assert guarded("s3cret").get("/x", headers=headers).status_code == 401


def test_service_token_accepts_the_right_token() -> None:
    assert guarded("s3cret").get("/x", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_empty_configured_token_fails_closed() -> None:
    assert guarded("").get("/x", headers={"Authorization": "Bearer "}).status_code == 401


def test_log_lines_are_json_with_context_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.chat_id = "c1"
    line = json.loads(JsonLineFormatter("gateway").format(record))
    assert line["msg"] == "hello world" and line["chat_id"] == "c1" and line["service"] == "gateway"


def test_configured_data_root_wins(tmp_path) -> None:
    assert data_root(str(tmp_path)) == tmp_path.resolve()
