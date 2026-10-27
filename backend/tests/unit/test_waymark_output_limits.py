"""A-1: real Node children must be stopped while producing excessive output."""
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import waymark_adapter as adapter


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_noisy_child_output_is_bounded_and_reaped(tmp_path, monkeypatch, stream):
    script = tmp_path / "noisy.mjs"
    script.write_text("import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; "
                      "fs.mkdtempSync(path.join(os.tmpdir(), 'patchdiff-waymark-')); "
                      f"setInterval(() => process.{stream}.write('x'.repeat(65536)), 1);", encoding="utf-8")
    children = []
    popen = subprocess.Popen

    def track(*args, **kwargs):
        child = popen(*args, **kwargs)
        child.temp_root = kwargs["env"]["TMPDIR"]
        children.append(child)
        return child

    monkeypatch.setattr(adapter.subprocess, "Popen", track)
    completed = adapter._run_bounded_discovery([shutil.which("node"), str(script)], b"{}", 5, 4096, 4096)
    assert len(getattr(completed, stream)) == 4097
    assert len(completed.stdout) <= 4097 and len(completed.stderr) <= 4097
    assert children[0].returncode is not None
    assert children[0].stdout.closed and children[0].stderr.closed
    result = adapter.discover_symbols_from_content(filename="x.py", content="X=1", discover_script=script,
                                                   max_stdout_bytes=4096, max_stderr_bytes=4096)
    assert result.error.code == "WAYMARK_OUTPUT_TOO_LARGE"
    assert stream in result.error.message
    assert all(child.poll() is not None for child in children)
    assert all(not Path(child.temp_root).exists() for child in children)


def test_real_hung_child_times_out_is_reaped_and_closes_pipes(tmp_path, monkeypatch):
    script = tmp_path / "hung.mjs"
    script.write_text("import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; "
                      "fs.mkdtempSync(path.join(os.tmpdir(), 'patchdiff-waymark-')); "
                      "setInterval(() => {}, 1000);", encoding="utf-8")
    children = []
    popen = subprocess.Popen

    def track(*args, **kwargs):
        child = popen(*args, **kwargs)
        child.temp_root = kwargs["env"]["TMPDIR"]
        children.append(child)
        return child

    monkeypatch.setattr(adapter.subprocess, "Popen", track)
    result = adapter.discover_symbols_from_content(filename="x.py", content="X=1", discover_script=script,
                                                   timeout_seconds=0.25)
    assert result.error.code == "WAYMARK_TIMEOUT"
    assert children[0].returncode is not None
    assert children[0].stdout.closed and children[0].stderr.closed
    assert not Path(children[0].temp_root).exists()


def test_simultaneous_pipes_at_inclusive_limits_do_not_deadlock(tmp_path):
    script = tmp_path / "both.mjs"
    script.write_text("process.stdout.write('o'.repeat(131072)); process.stderr.write('e'.repeat(131072));", encoding="utf-8")
    completed = adapter._run_bounded_discovery([shutil.which("node"), str(script)], b"{}", 5, 131072, 131072)
    assert completed.returncode == 0
    assert completed.stdout == b"o" * 131072 and completed.stderr == b"e" * 131072
