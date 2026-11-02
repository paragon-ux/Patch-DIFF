"""CI-only operator provisioning and private environment for disposable services.

No credential enters GITHUB_ENV, tool payloads or the model/service environment.
The managed runtime preserves containers and volumes when stopped.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from app.core.config import redact_sensitive_text
from app.mcp.runtime_cli import (
    build_database_url, ensure_runtime_credentials, run_setup_command,
)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Expected setup or run <command>.")
    if sys.argv[1] == "setup":
        result=run_setup_command()
        assert result["status"] == "ready",result
        print("Disposable CI runtime migrated and both MCP roles verified.")
        return
    if sys.argv[1] != "run" or len(sys.argv) < 3:
        raise SystemExit("Expected run <command>.")
    creds=ensure_runtime_credentials()
    env=dict(os.environ)
    import json
    bootstrap=json.loads(Path(creds["bootstrap_credentials_file"]).read_text())
    for role in ("bootstrap","host","agent"):
        env[f"PATCHDIFF_{role.upper()}_DATABASE_URL"]=build_database_url(
            bootstrap["port"],host=bootstrap["host"],dbname=creds["dbname"],role=role,creds=creds)
    env.pop("PATCHDIFF_DATABASE_URL",None)
    raise SystemExit(subprocess.run(sys.argv[2:],env=env).returncode)


if __name__ == "__main__":
    try:main()
    except Exception as exc:
        raise SystemExit(redact_sensitive_text(str(exc))) from None
