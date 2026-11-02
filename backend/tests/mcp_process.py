"""Role-correct subprocess launches for source integration tests.

The root/CI operator launches editor children as the service user. Application
security checks remain enabled; the test harness never runs a model as service.
"""
from __future__ import annotations

import os
import subprocess


def _launch(args, kwargs):
    if isinstance(args, (list, tuple)) and "app.mcp.external_adapter" in args:
        env = dict(kwargs.get("env", os.environ))
        profile = env.get("PATCHDIFF_MCP_PROFILE", "observed_v2")
        role = "HOST" if profile == "full" else "AGENT"
        role_url = env.get(f"PATCHDIFF_{role}_DATABASE_URL")
        if role_url:
            env["PATCHDIFF_DATABASE_URL"] = role_url
        for key in tuple(env):
            if key.startswith("PATCHDIFF_") and any(part in key for part in ("BOOTSTRAP", "HOST_", "AGENT_", "ADMIN_")):
                if key != f"PATCHDIFF_{role}_DATABASE_URL":
                    env.pop(key)
        if profile != "full" and profile != "unknown":
            # The source interpreter and checkout must be readable by the
            # service, just as the installed runtime must be in deployment.
            preserved = [key for key in env if key.startswith(("PATCHDIFF_", "PYTHON", "PGAPPNAME"))]
            args = ["sudo", "-n", "-u", "patchdiff-mcp-agent",
                    "--preserve-env="+",".join(preserved), "--", *args]
        kwargs["env"] = env
    return args, kwargs


def mcp_popen(args, **kwargs):
    args, kwargs = _launch(args, kwargs)
    return subprocess.Popen(args, **kwargs)


def mcp_run(args, **kwargs):
    args, kwargs = _launch(args, kwargs)
    return subprocess.run(args, **kwargs)
