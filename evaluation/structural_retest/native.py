"""Arm A broker: original native tool semantics within five confined files."""
from __future__ import annotations

import asyncio
import shlex
import hashlib
from pathlib import Path


def confined(root: Path, value: str, names: set[str]) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or path.parent != root.resolve() or path.name not in names or path.is_symlink():
        raise PermissionError("Native path outside arm target files")
    # Check the original path as well: resolving must not hide a symlink.
    if (root / value).is_symlink():
        raise PermissionError("Native symlinks forbidden")
    return path


class NativeTools:
    def __init__(self, root: Path, names: set[str], rtk_path: str):
        self.root, self.names, self.rtk = root, names, rtk_path

    async def call(self, name: str, arguments: dict):
        if name == "edit_file":
            if set(arguments) != {"Path", "Target", "Replacement"} or not arguments["Target"]:
                raise ValueError("Native edit_file requires Path, nonempty Target and Replacement")
            path = confined(self.root, arguments["Path"], self.names)
            old, new = arguments["Target"].encode("utf-8"), arguments["Replacement"].encode("utf-8")
            data = path.read_bytes()
            count = data.count(old)
            if not count:
                return {"status": "rejected", "error": "exact_target_absent"}
            path.write_bytes(data.replace(old, new))
            return {"status": "accepted", "occurrences_replaced": count}
        if name != "run_command" or set(arguments) != {"command"}:
            raise PermissionError("Unauthorized native tool/arguments")
        parts = shlex.split(arguments["command"], posix=True)
        if len(parts) != 3 or parts[:2] != ["rtk", "read"]:
            raise PermissionError("Only rtk read ONE confined file is permitted")
        path = confined(self.root, parts[2], self.names)
        process = await asyncio.create_subprocess_exec(self.rtk, "read", str(path), cwd=str(self.root),
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            return {"status": "rejected", "error": "rtk_read_failed", "exit_code": process.returncode}
        return {"status": "ok", "content": stdout.decode("utf-8")}


async def verify_binding(binding: dict, configured_path: str | None) -> list[str]:
    if not configured_path or not binding:
        return ["A: unresolved native executable binding"]
    executable = Path(configured_path).resolve()
    if (not executable.is_file() or str(executable) != str(Path(binding.get("executable_path", "")).resolve())
            or hashlib.sha256(executable.read_bytes()).hexdigest() != binding.get("sha256")):
        return ["A: native executable differs from reviewed binding"]
    probe = await asyncio.create_subprocess_exec(str(executable), "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        stdout, _ = await asyncio.wait_for(probe.communicate(), 30)
    except BaseException:
        if probe.returncode is None:
            probe.kill()
            await probe.wait()
        raise
    return [] if probe.returncode == 0 and stdout.decode("utf-8").strip() == binding.get("version_output") else ["A: native version differs from reviewed binding"]
