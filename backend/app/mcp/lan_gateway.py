"""One supervised PatchDIFF run over MCP Streamable HTTP (JSON responses)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_workspace_root, is_strict_observation_mode_enabled
from app.mcp.external_adapter import ExternalMCPAdapter, LATEST_PROTOCOL_VERSION
from app.services.waymark_worker import serving_worker_owner
from app.services.workspace_sync_service import validate_workspace_root
from app.storage.db import database_schema_is_current, engine

LOG = logging.getLogger("uvicorn.error")
HTTP_PROTOCOL_VERSIONS = frozenset({"2025-06-18", "2025-11-25"})
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_SESSIONS = 256
MAX_ADMITTED = 64
SESSION_IDLE_SECONDS = 3600
SESSION_HEADER = "MCP-Session-Id"
VERSION_HEADER = "MCP-Protocol-Version"
TRACE_HEADER = "PatchDIFF-Request-Id"


@dataclass(frozen=True)
class Credentials:
    # Maps an operator-defined identity to a SHA-256 bearer digest, never raw tokens.
    workers: dict[str, str]
    trusted: dict[str, str]
    operator: str

    def __post_init__(self) -> None:
        if not isinstance(self.workers, dict) or not self.workers or not isinstance(self.trusted, dict):
            raise ValueError("Expected a nonempty workers map and a trusted map.")
        if any(not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name)
               for name in (*self.workers, *self.trusted)):
            raise ValueError("Principal names must be short non-secret identifiers.")
        digests = [*self.workers.values(), *self.trusted.values(), self.operator]
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in digests) or len(set(digests)) != len(digests):
            raise ValueError("Each credential must have a distinct lowercase SHA-256 digest.")


@dataclass
class Session:
    principal: str
    route: str
    adapter: ExternalMCPAdapter
    version: str
    last_used: float
    trace_id: str
    ready: bool = False
    inflight: int = 0


class Gateway:
    def __init__(self, run_id: str, credentials: Credentials, profile: str, origins: frozenset[str]):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", run_id):
            raise ValueError("Run ID must be a short non-secret identifier.")
        if profile == "full":
            raise ValueError("The full profile is reserved for the trusted route.")
        ExternalMCPAdapter(profile=profile)  # Reject unsupported profile at startup.
        self.run_id = run_id
        self.credentials = credentials
        self.profile = profile
        self.origins = origins
        self.sessions: dict[str, Session] = {}
        self.accepting = True
        self.inflight: set[asyncio.Task] = set()

    def authenticate(self, request: Request, route: str) -> str:
        origin = request.headers.getlist("origin")
        if origin and (len(origin) != 1 or origin[0] not in self.origins):
            raise HTTPException(403, "Origin is not allowed.")
        headers = request.headers.getlist("authorization")
        scheme, _, token = headers[0].partition(" ") if len(headers) == 1 else ("", "", "")
        if scheme.lower() == "bearer" and re.fullmatch(r"[A-Za-z0-9._~+/-]{32,512}={0,2}", token):
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
            identities = ({"operator": self.credentials.operator} if route == "operator"
                          else self.credentials.trusted if route == "trusted" else self.credentials.workers)
            principal = next((name for name, expected in identities.items()
                              if hmac.compare_digest(digest, expected)), None)
            if principal is not None:
                return principal
        raise HTTPException(401, "A valid bearer credential is required.",
                            headers={"WWW-Authenticate": "Bearer"})

    def get_session(self, session_id: str | None, principal: str, route: str) -> Session:
        if session_id is None:
            raise HTTPException(400, "MCP-Session-Id is required.")
        session = self.sessions.get(session_id)
        if session is not None and not session.inflight and time.monotonic() - session.last_used > SESSION_IDLE_SECONDS:
            del self.sessions[session_id]
            session = None
        if session is None or session.principal != principal or session.route != route:
            raise HTTPException(404, "MCP session is unavailable.")
        session.last_used = time.monotonic()
        return session

    def new_session(self, principal: str, route: str, message: dict) -> Response:
        now = time.monotonic()
        self.sessions = {key: session for key, session in self.sessions.items()
                         if session.inflight or now - session.last_used <= SESSION_IDLE_SECONDS}
        if len(self.sessions) >= MAX_SESSIONS:
            raise HTTPException(503, "Session limit reached.")
        adapter = ExternalMCPAdapter(profile="full" if route == "trusted" else self.profile)
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("protocolVersion"), str):
            raise HTTPException(400, "initialize requires a protocolVersion.")
        # The stdio adapter also supports the older, stdio-only fallback.
        if params["protocolVersion"] not in HTTP_PROTOCOL_VERSIONS:
            message = {**message, "params": {**params, "protocolVersion": LATEST_PROTOCOL_VERSION}}
        result = adapter.handle_request(message)
        if result is None or "result" not in result:
            return JSONResponse(result, status_code=400)
        session_id = secrets.token_urlsafe(32)
        self.sessions[session_id] = Session(principal, route, adapter, result["result"]["protocolVersion"],
                                            now, secrets.token_hex(12))
        return JSONResponse(result, headers={SESSION_HEADER: session_id})

    def drain(self) -> dict[str, Any]:
        self.accepting = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "accepting": self.accepting, "inflight": len(self.inflight)}

    async def dispatch(self, session: Session, message: dict) -> Response:
        # No await between the admission check and registration on this single event loop.
        if not self.accepting or len(self.inflight) >= MAX_ADMITTED:
            raise HTTPException(503, "The run is closed to admission or at capacity.")
        trace_id = secrets.token_hex(12)
        session.inflight += 1
        task = asyncio.create_task(self._execute(session, message, trace_id))
        self.inflight.add(task)
        task.add_done_callback(self.inflight.discard)
        reply = await asyncio.shield(task)
        if reply is None:
            return Response(status_code=202, headers={TRACE_HEADER: trace_id})
        return JSONResponse(reply, headers={TRACE_HEADER: trace_id})

    async def _execute(self, session: Session, message: dict, trace_id: str) -> dict | None:
        start = time.monotonic_ns()
        name = message.get("params", {}).get("name") if isinstance(message.get("params"), dict) else None
        tool = name if message["method"] == "tools/call" and name in session.adapter._tool_names else "-"
        try:
            return await asyncio.to_thread(session.adapter.handle_request, message, redact_internal_errors=True)
        except Exception:
            # Log correlation without input, credentials, workspace paths or database diagnostics.
            LOG.error("patchdiff_mcp_dispatch_failed run=%s request=%s", self.run_id, trace_id)
            return {"jsonrpc": "2.0", "id": message["id"],
                    "error": {"code": -32603, "message": "Tool outcome unknown."}}
        finally:
            session.inflight -= 1
            session.last_used = time.monotonic()
            LOG.info("patchdiff_mcp run=%s route=%s session=%s request=%s tool=%s start_ns=%s end_ns=%s",
                     self.run_id, session.route, session.trace_id, trace_id, tool, start, time.monotonic_ns())


def _single_header(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise HTTPException(400, f"Expected one {name} header.")
    return values[0] if values else None


def _accepts(request: Request, media_type: str) -> bool:
    for value in request.headers.getlist("accept"):
        for entry in value.split(","):
            media, *parameters = entry.split(";")
            if media.strip().lower() != media_type:
                continue
            qualities = [value.strip() for parameter in parameters
                         for key, separator, value in [parameter.partition("=")]
                         if key.strip().lower() == "q" and separator]
            if not qualities:
                return True
            if (len(qualities) == 1 and re.fullmatch(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)", qualities[0])
                    and float(qualities[0]) > 0):
                return True
    return False


async def _message(request: Request) -> dict:
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Expected application/json.")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request body exceeds the size limit.")
        data.extend(chunk)
    try:
        message = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "Expected one UTF-8 JSON-RPC message.") from exc
    if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
            or ("id" in message and type(message["id"]) not in (int, str))
            or ("method" in message and not isinstance(message["method"], str))):
        raise HTTPException(400, "Invalid JSON-RPC message.")
    return message


def create_app(run_id: str, credentials: Credentials, *, profile: str = "observed_workspace",
               origins: frozenset[str] = frozenset()) -> FastAPI:
    gateway = Gateway(run_id, credentials, profile, origins)

    @asynccontextmanager
    async def lifespan(app):
        if not get_workspace_root() or not os.environ.get("PATCHDIFF_DATABASE_URL"):
            raise RuntimeError("LAN startup requires an explicit workspace root and database URL.")
        validate_workspace_root(get_workspace_root())
        if profile == "workspace" and is_strict_observation_mode_enabled():
            raise RuntimeError("Strict observation requires an observed profile.")
        if not database_schema_is_current():
            raise RuntimeError("Apply the installed Alembic migrations before starting the gateway.")
        with serving_worker_owner():
            try:
                yield
            finally:
                gateway.drain()
                if gateway.inflight:
                    await asyncio.gather(*gateway.inflight)
                await asyncio.to_thread(engine.dispose)

    app = FastAPI(lifespan=lifespan, openapi_url=None, redirect_slashes=False)

    async def mcp(request: Request, route: str) -> Response:
        principal = gateway.authenticate(request, route)
        version = _single_header(request, VERSION_HEADER)
        if version is not None and version not in HTTP_PROTOCOL_VERSIONS:
            raise HTTPException(400, "Unsupported MCP protocol version.")
        session_id = _single_header(request, SESSION_HEADER)
        if not gateway.accepting:
            raise HTTPException(503, "The run is closed to admission.")
        if request.method == "POST":
            if not (_accepts(request, "application/json") and _accepts(request, "text/event-stream")):
                raise HTTPException(406, "Accept must include application/json and text/event-stream.")
            message = await _message(request)
            if not gateway.accepting:
                raise HTTPException(503, "The run is closed to admission.")
            method = message.get("method")
            if method == "initialize" and session_id is None:
                if "id" not in message:
                    raise HTTPException(400, "initialize requires a request ID.")
                return gateway.new_session(principal, route, message)
        session = gateway.get_session(session_id, principal, route)
        if version is not None and version != session.version:
            raise HTTPException(400, "MCP protocol version differs from the negotiated session.")
        if request.method == "GET":
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})
        if request.method == "DELETE":
            del gateway.sessions[session_id]
            return Response(status_code=204)
        if method == "initialize":
            raise HTTPException(400, "Start a new MCP session to initialize.")
        if "id" not in message or method is None:
            if method == "notifications/initialized" and "id" not in message:
                session.ready = True
            elif not (isinstance(method, str) and method.startswith("notifications/") and "id" not in message
                      or method is None and "id" in message and ("result" in message) != ("error" in message)):
                raise HTTPException(400, "Expected a request or notification.")
            return Response(status_code=202)
        if method == "ping":
            return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        if not session.ready:
            raise HTTPException(400, "Send notifications/initialized before requesting tools.")
        return await gateway.dispatch(session, message)

    @app.api_route("/mcp", methods=["POST", "GET", "DELETE"])
    async def worker_mcp(request: Request) -> Response:
        return await mcp(request, "worker")

    if credentials.trusted:
        @app.api_route("/trusted/mcp", methods=["POST", "GET", "DELETE"])
        async def trusted_mcp(request: Request) -> Response:
            return await mcp(request, "trusted")

    @app.api_route("/operator/drain", methods=["POST", "GET"])
    async def drain(request: Request) -> dict:
        gateway.authenticate(request, "operator")
        return gateway.drain() if request.method == "POST" else gateway.status()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--profile", default="observed_workspace")
    parser.add_argument("--origin", action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    args = parser.parse_args()
    if bool(args.tls_cert) != bool(args.tls_key) or (
        args.host not in {"127.0.0.1", "::1"} and not args.tls_cert
    ):
        parser.error("Supply both TLS files when binding beyond loopback.")
    try:
        with args.credentials_file.open(encoding="utf-8") as source:
            credentials = Credentials(**json.load(source))
        app = create_app(args.run_id, credentials, profile=args.profile, origins=frozenset(args.origin))
    except (OSError, ValueError, TypeError):
        parser.error("Invalid gateway configuration or credentials file.")
    uvicorn.run(app, host=args.host, port=args.port, workers=1, access_log=False, proxy_headers=False,
                ssl_certfile=args.tls_cert, ssl_keyfile=args.tls_key)


if __name__ == "__main__":
    main()
