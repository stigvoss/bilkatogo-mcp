import json
import os
import stat

import pytest
from conftest import FakeGigya

pytestmark = pytest.mark.anyio


async def test_pasted_token_is_used_and_saved(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="pasted")
    FakeGigya({"pasted"}).install(server)
    _, source = await server._get_jwt()
    assert source == "BILKATOGO_LOGIN_TOKEN"
    assert json.loads(server.STATE_FILE.read_text())["login_token"] == "pasted"
    assert stat.S_IMODE(os.stat(server.STATE_FILE).st_mode) == 0o600


async def test_saved_token_works_without_config(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="pasted")
    FakeGigya({"pasted"}).install(server)
    await server._get_jwt()

    server = load_server(BILKATOGO_STATE_FILE=str(server.STATE_FILE))
    FakeGigya({"pasted"}).install(server)
    _, source = await server._get_jwt()
    assert source == "state file"


async def test_expired_token_without_credentials_explains_itself(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="stale")
    FakeGigya().install(server)
    with pytest.raises(server.AuthError, match="no BILKATOGO_EMAIL"):
        await server._get_jwt()


async def test_expired_token_with_credentials_logs_in_again(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="stale", BILKATOGO_EMAIL="a@b.c", BILKATOGO_PASSWORD="pw")
    FakeGigya({"fresh-token"}).install(server)
    _, source = await server._get_jwt()
    assert source == "email/password login"
    assert json.loads(server.STATE_FILE.read_text())["login_token"] == "fresh-token"


async def test_bad_password_error_does_not_leak_it(load_server):
    server = load_server(BILKATOGO_EMAIL="a@b.c", BILKATOGO_PASSWORD="wrong-password")
    FakeGigya().install(server)
    with pytest.raises(server.AuthError) as error:
        await server._get_jwt()
    assert "403042" in str(error.value)
    assert "wrong-password" not in str(error.value)


async def test_jwt_is_cached(load_server):
    server = load_server(BILKATOGO_LOGIN_TOKEN="pasted")
    gigya = FakeGigya({"pasted"})
    gigya.install(server)
    await server._get_jwt()
    calls = len(gigya.calls)
    await server._get_jwt()
    assert len(gigya.calls) == calls


def test_startup_requires_a_login_source(load_server):
    server = load_server()
    with pytest.raises(SystemExit, match="No Bilka login configured"):
        server._check_login_sources()


def test_startup_rejects_email_without_password(load_server):
    server = load_server(BILKATOGO_EMAIL="a@b.c")
    with pytest.raises(SystemExit, match="both"):
        server._check_login_sources()


def test_unreadable_secret_file_explains_how_to_fix_it(load_server, tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(SystemExit, match="PUID"):
        load_server(BILKATOGO_LOGIN_TOKEN_FILE=str(missing))
