"""Evaluator-owned real stdio MCP sessions and isolated disposable databases."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

from evaluation.structural_retest.host_adapter import JsonLinePeer, TOOLS

REPO = Path(__file__).resolve().parents[2]


def eol_facts(data: bytes) -> dict:
    text = data.decode("utf-8")
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    kinds = [key for key, n in (("lf", lf), ("crlf", crlf), ("cr", cr)) if n]
    return {"style": "none" if not kinds else kinds[0] if len(kinds) == 1 else "mixed",
            "lf": lf, "crlf": crlf, "cr": cr, "normalized": bool(cr or crlf),
            "source_code_points": len(text), "source_utf8_bytes": len(data),
            "source_sha256": hashlib.sha256(data).hexdigest()}


class MCPSession(JsonLinePeer):
    def __init__(self, database_url: str, arm: str):
        self.arm = arm
        env = {**os.environ, "PYTHONPATH": str(REPO / "backend"), "PATCHDIFF_DATABASE_URL": database_url,
               "PATCHDIFF_STRICT_OBSERVATION_MODE": "true" if arm == "C" else "false"}
        super().__init__([sys.executable, "-m", "app.mcp.external_adapter"], cwd=str(REPO), env=env)
        self.targets = {}

    async def start(self):
        await super().start()
        await self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                          "clientInfo": {"name": "retest-controller", "version": "1"}})
        schemas = await self.request("tools/list", {})
        self.schemas = schemas
        if not (TOOLS[self.arm] | {"patchdiff_initialize_target", "patchdiff_get_target", "patchdiff_export_target",
                                  "patchdiff_get_pdcp_log", "patchdiff_get_manifest_ledger"}) <= {t["name"] for t in schemas["tools"]}:
            raise ValueError("Missing required real MCP tools")

    async def call(self, name: str, arguments: dict):
        result = await self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError") or len(result.get("content", [])) != 1:
            raise RuntimeError("MCP tool/protocol error")
        return json.loads(result["content"][0]["text"])

    async def initialize(self, sources: dict[str, bytes], call):
        for name, data in sources.items():
            args = {"filename": name, "content": data.decode("utf-8"),
                    "content_type": {".py": "text/x-python", ".json": "application/json", ".md": "text/markdown"}[Path(name).suffix]}
            result = await call("patchdiff_initialize_target", args)
            if result.get("status") != "ok":
                raise ValueError("MCP initialization failed")
            target_id = str(uuid.UUID(result["target_file_id"]))
            if target_id in self.targets.values():
                raise ValueError("Duplicate fresh target ID")
            self.targets[name] = target_id
            target = await call("patchdiff_get_target", {"target_file_id": target_id})
            canonical = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if (target.get("version") != 0 or target.get("current_content") != canonical
                    or target.get("current_hash") != hashlib.sha256(canonical.encode()).hexdigest()
                    or target.get("source_line_endings") != eol_facts(data)
                    or result.get("current_hash") != target["current_hash"] or result.get("version") != 0):
                raise ValueError("Initial target hash/version/EOL verification failed")
        return self.targets


async def disposable_database(admin_url: str, evidence) -> str:
    """Only administrative SQL creates a new DB; all target mutations use MCP.

    Never drop a database automatically. Retain databases through review/archive;
    their random names are recorded for explicit owner cleanup later.
    """
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url
    admin = make_url(admin_url)
    database_name = "retest_" + uuid.uuid4().hex
    # Synchronous psycopg in a worker also works with Windows' subprocess-capable
    # Proactor loop; psycopg's async connection requires a different Windows loop.
    def create():
        with psycopg.connect(admin.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True,
                             connect_timeout=30, options="-c statement_timeout=30000") as connection:
            postgres_version = connection.execute("SHOW server_version").fetchone()[0]
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
            return postgres_version
    postgres_version = await asyncio.to_thread(create)
    database_url = admin.set(drivername="postgresql+psycopg", database=database_name).render_as_string(hide_password=False)
    evidence.emit("disposable_database_created", database_name=database_name, postgres_version=postgres_version, retained=True)
    env = {**os.environ, "PATCHDIFF_DATABASE_URL": database_url, "PYTHONPATH": str(REPO / "backend")}
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "-c", "backend/app/migrations/alembic.ini", "upgrade", "head",
                                                   cwd=str(REPO), env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        if await asyncio.wait_for(process.wait(), 60) != 0:
            raise RuntimeError("Disposable database migration failed")
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return database_url
