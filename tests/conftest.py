import importlib
import sys

import httpx
import pytest

API_KEY = "test-key-0123456789abcdefghijklmnop"
LOGIN_ENV = ("BILKATOGO_LOGIN_TOKEN", "BILKATOGO_EMAIL", "BILKATOGO_PASSWORD")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def load_server(monkeypatch, tmp_path):
    """Import a fresh copy of server.py under the given environment."""

    def load(**env):
        for name in LOGIN_ENV:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("MCP_API_KEY", API_KEY)
        monkeypatch.setenv("BILKATOGO_STATE_FILE", str(tmp_path / "session.json"))
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        sys.modules.pop("server", None)
        return importlib.import_module("server")

    yield load
    sys.modules.pop("server", None)


class FakeGigya:
    """Stands in for accounts.getJWT / accounts.login."""

    def __init__(self, good_tokens=(), good_login=("a@b.c", "pw")):
        self.good_tokens = set(good_tokens)
        self.good_login = good_login
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        self.calls.append(request.url.path)
        if request.url.path.endswith("accounts.getJWT"):
            token = form["login_token"]
            if token in self.good_tokens:
                return httpx.Response(200, json={"id_token": f"jwt-{token}"})
            return httpx.Response(403, json={"errorCode": 403005})
        if request.url.path.endswith("accounts.login"):
            if (form["loginID"], form["password"]) == self.good_login:
                return httpx.Response(200, json={"sessionInfo": {"cookieValue": "fresh-token"}})
            return httpx.Response(403, json={"errorCode": 403042})
        return httpx.Response(404)

    def install(self, server):
        server._client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
