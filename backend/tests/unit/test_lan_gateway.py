import asyncio
import hashlib
import threading

import httpx
import pytest

from app.mcp import lan_gateway

VERSION = "2025-11-25"
ACCEPT = "application/json, text/event-stream"
ALICE = "a" * 32
BOB = "b" * 32
TRUSTED = "c" * 32
OPERATOR = "d" * 32


def digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def rpc(method, params=None, *, request_id=1):
    message = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    if request_id is not None:
        message["id"] = request_id
    return message


def headers(token, session=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": ACCEPT}
    if session is not None:
        headers.update({"MCP-Session-Id": session, "MCP-Protocol-Version": VERSION})
    return headers


def app_client():
    credentials = lan_gateway.Credentials({"alice": digest(ALICE), "bob": digest(BOB)},
                                          {"verifier": digest(TRUSTED)}, digest(OPERATOR))
    app = lan_gateway.create_app("demo", credentials, profile="observed_workspace",
                                 origins=frozenset({"https://ui.example"}))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://lan.example")


async def initialize(client, token=ALICE, route="/mcp"):
    response = await client.post(route, headers=headers(token),
                                 json=rpc("initialize", {"protocolVersion": VERSION, "capabilities": {}}))
    assert response.status_code == 200
    session = response.headers["MCP-Session-Id"]
    response = await client.post(route, headers=headers(token, session),
                                 json=rpc("notifications/initialized", request_id=None))
    assert response.status_code == 202 and not response.content
    return session


def test_remote_auth_session_scope_and_profile_are_independent():
    async def scenario():
        async with app_client() as client:
            first, second = await initialize(client), await initialize(client, BOB)
            trusted = await initialize(client, TRUSTED, "/trusted/mcp")
            assert len({first, second, trusted}) == 3
            listing = rpc("tools/list")
            assert (await client.post("/mcp", json=listing)).status_code == 401
            assert (await client.post("/mcp", headers=headers(BOB, first), json=listing)).status_code == 404
            assert (await client.post("/trusted/mcp", headers=headers(ALICE, first), json=listing)).status_code == 401
            assert (await client.get("/operator/drain", headers=headers(ALICE))).status_code == 401

            worker_headers = headers(ALICE, first)
            denied = await client.post("/mcp", headers={**worker_headers, "Origin": "https://other.example"},
                                       json=listing)
            assert denied.status_code == 403
            bad_version = await client.post("/mcp", headers={**worker_headers, "MCP-Protocol-Version": "2024-11-05"},
                                            json=listing)
            assert bad_version.status_code == 400
            for quality in ("Q = 0.0", "q=-0.4", "q=word"):
                invalid_accept = {**worker_headers, "Accept": f"application/json, text/event-stream;{quality}"}
                assert (await client.post("/mcp", headers=invalid_accept, json=listing)).status_code == 406

            worker = await client.post("/mcp", headers=worker_headers, json=listing)
            assert worker.status_code == 200
            worker_names = {tool["name"] for tool in worker.json()["result"]["tools"]}
            assert worker_names == set(lan_gateway.ExternalMCPAdapter(profile="observed_workspace")._tool_names)
            privileged = await client.post("/trusted/mcp", headers=headers(TRUSTED, trusted), json=listing)
            assert privileged.status_code == 200
            assert "patchdiff_export_target" in {tool["name"] for tool in privileged.json()["result"]["tools"]}
            denied_tool = await client.post("/mcp", headers=worker_headers, json=rpc("tools/call", {
                "name": "patchdiff_export_target", "arguments": {},
            }))
            assert denied_tool.json()["result"]["isError"] is True

            assert (await client.get("/mcp", headers=worker_headers)).status_code == 405
            assert (await client.delete("/mcp", headers=worker_headers)).status_code == 204
            assert (await client.post("/mcp", headers=worker_headers, json=listing)).status_code == 404
            assert (await client.post("/mcp", headers=headers(BOB, second), json=listing)).status_code == 200

    asyncio.run(scenario())


def test_drain_counts_already_admitted_work_even_after_client_cancellation(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    old_handle = lan_gateway.ExternalMCPAdapter.handle_request

    def handle(adapter, message, **kwargs):
        if message["method"] == "tools/list" and message["id"] == 2:
            entered.set()
            assert release.wait(5)
        return old_handle(adapter, message, **kwargs)

    monkeypatch.setattr(lan_gateway.ExternalMCPAdapter, "handle_request", handle)

    async def scenario():
        async with app_client() as client:
            worker = await initialize(client)
            trusted = await initialize(client, TRUSTED, "/trusted/mcp")
            request = asyncio.create_task(client.post("/mcp", headers=headers(ALICE, worker),
                                                      json=rpc("tools/list", request_id=2)))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
                status = await client.post("/operator/drain", headers=headers(OPERATOR))
                assert status.json() == {"run_id": "demo", "accepting": False, "inflight": 1}
                new_work = await client.post("/trusted/mcp", headers=headers(TRUSTED, trusted),
                                             json=rpc("tools/list"))
                assert new_work.status_code == 503
            finally:
                release.set()
            async with asyncio.timeout(5):
                while (await client.get("/operator/drain", headers=headers(OPERATOR))).json()["inflight"]:
                    await asyncio.sleep(0.01)

    asyncio.run(scenario())


def test_gateway_redacts_backend_exception(monkeypatch):
    from app.mcp.external_adapter import registry

    def broken(*args, **kwargs):
        raise RuntimeError("private DSN or SQL parameters")

    monkeypatch.setattr(type(registry), "call", broken)

    async def scenario():
        async with app_client() as client:
            session = await initialize(client)
            reply = await client.post("/mcp", headers=headers(ALICE, session), json=rpc("tools/call", {
                "name": "patchdiff_initialize_target", "arguments": {"filename": "demo.py", "from_workspace": True},
            }))
            assert reply.json()["result"]["isError"]
            assert "private" not in reply.text
            assert "outcome is unknown" in reply.text

    asyncio.run(scenario())
