"""Owner-supplied host bridge protocol. No provider/model is selected here.

The bridge is trusted operator code, outside the measured sandbox. It must use
provider evidence, enforce the sandbox and cancellation, and expose only the
controller's tool broker. A description alone cannot enforce those guarantees.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

from evaluation.structural_retest.telemetry import wire

INTERFACE_VERSION = "patchdiff-retest-host/1"
TOOLS = {
    "A": {"run_command", "edit_file"},
    "B": {"patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_submit_edits", "patchdiff_save", "patchdiff_replay"},
    "C": {"patchdiff_observe_scope", "patchdiff_read_target", "patchdiff_find_occurrences", "patchdiff_submit_observed_operations", "patchdiff_save", "patchdiff_replay"},
}
SEMANTICS = {"run_command": "rtk-read-one-confined-file", "edit_file": "replace-all-exact-Target-with-Replacement",
             "mcp": "real-stdio-patchdiff", "C": "server-strict-observation"}
CAPABILITIES = {"fresh_context", "broker_only_tools", "filesystem_denied", "network_denied",
                "cancel_inflight", "actual_usage", "hard_total_token_limit", "no_transport_retries"}
HOST_FIELDS = ("provider", "exact_provider_model_id", "effective_reasoning_setting", "host_name", "host_version",
               "decoding_settings", "context_limit", "output_limit", "tool_permissions", "model_configuration_timestamp")


class HostAdapter(Protocol):
    synthetic: bool
    async def describe(self) -> dict: ...
    async def open_context(self, specification: dict) -> str: ...
    async def turn(self, context_id: str, tool_results: list[dict], limits: dict) -> dict: ...
    async def close_context(self, context_id: str) -> None: ...


class JsonLinePeer:
    """One outstanding request, bounded response; cancellation kills the child.

    Framing is UTF-8 JSON lines (not Content-Length). No automatic retry occurs.
    Child stderr is discarded: credentials must not leak through host diagnostics.
    """
    def __init__(self, command: list[str], *, cwd=None, env=None):
        self.command, self.cwd, self.env = command, cwd, env
        self.process = None
        self.counter = 0
        self.trace = None

    async def start(self):
        self.process = await asyncio.create_subprocess_exec(*self.command, cwd=self.cwd, env=self.env,
                                                          stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                          stderr=asyncio.subprocess.DEVNULL, limit=4 * 1024 * 1024)

    async def request(self, method, params):
        import json
        self.counter += 1
        message = {"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params}
        try:
            if self.process is None or self.process.returncode is not None:
                raise ConnectionError("Bridge/MCP process is not running")
            request_bytes = wire(message) + b"\n"
            if self.trace:
                self.trace("jsonrpc_request", message, request_bytes)
            self.process.stdin.write(request_bytes)
            await self.process.stdin.drain()
            response_bytes = await self.process.stdout.readline()
            if not response_bytes:
                raise ConnectionError("Bridge/MCP peer disconnected")
            response = json.loads(response_bytes)
            if self.trace:
                self.trace("jsonrpc_response", response, response_bytes)
            if response.get("id") != self.counter or "error" in response:
                raise RuntimeError("Bridge/MCP protocol error")
            return response["result"]
        except asyncio.CancelledError:
            await self.close()
            raise
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise ConnectionError("Bridge/MCP peer disconnected") from exc

    async def close(self, *, graceful=False):
        if self.process:
            if graceful and self.process.returncode is None:
                self.process.stdin.close()
                try:
                    await asyncio.wait_for(self.process.wait(), 1)
                    return
                except TimeoutError:
                    pass
            if self.process.returncode is None:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
            # wait() also reaps a peer that exited by itself before cleanup.
            await asyncio.wait_for(self.process.wait(), 30)


class BridgeHost(JsonLinePeer):
    synthetic = False

    async def describe(self):
        return await self.request("host/describe", {"interface_version": INTERFACE_VERSION})

    async def open_context(self, specification):
        result = await self.request("host/open", specification)
        if result.get("permissions_applied") is not True or result.get("fresh_context") is not True:
            raise ValueError("Host did not apply isolated fresh-context permissions")
        return result["context_id"]

    async def turn(self, context_id, tool_results, limits):
        return await self.request("host/turn", {"context_id": context_id, "tool_results": tool_results, "limits": limits})

    async def close_context(self, context_id):
        await self.request("host/close", {"context_id": context_id, "cancel_inflight": True})
