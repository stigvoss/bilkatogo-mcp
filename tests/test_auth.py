import httpx
import pytest
from conftest import API_KEY

pytestmark = pytest.mark.anyio


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _client(server, **limits):
    for name, value in limits.items():
        setattr(server, name, value)
    app = server.ApiKeyMiddleware(_ok_app)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_missing_and_wrong_keys_are_rejected(load_server):
    async with _client(load_server(BILKATOGO_LOGIN_TOKEN="t")) as client:
        assert (await client.post("/mcp")).status_code == 401
        assert (await client.post("/mcp", headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await client.post("/mcp", headers={"Authorization": API_KEY})).status_code == 401


async def test_correct_key_passes(load_server):
    async with _client(load_server(BILKATOGO_LOGIN_TOKEN="t")) as client:
        response = await client.post("/mcp", headers={"Authorization": f"Bearer {API_KEY}"})
        assert response.status_code == 200


async def test_health_check_needs_no_key(load_server):
    async with _client(load_server(BILKATOGO_LOGIN_TOKEN="t")) as client:
        assert (await client.get("/healthz")).status_code == 200


async def test_repeated_bad_keys_lock_everyone_out_briefly(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="t")
    async with _client(server, AUTH_FAIL_LIMIT_PER_MIN=3) as client:
        for _ in range(3):
            await client.post("/mcp", headers={"Authorization": "Bearer nope"})
        good = await client.post("/mcp", headers={"Authorization": f"Bearer {API_KEY}"})
        assert good.status_code == 429
        assert (await client.get("/healthz")).status_code == 200


async def test_rate_limit(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="t")
    async with _client(server, RATE_LIMIT_PER_MIN=2) as client:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        statuses = [(await client.post("/mcp", headers=headers)).status_code for _ in range(3)]
        assert statuses == [200, 200, 429]
