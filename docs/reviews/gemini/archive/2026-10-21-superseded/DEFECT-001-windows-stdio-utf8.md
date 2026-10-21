# DEFECT-001: Windows Stdio Default Codepage Encoding Crash

- **Defect ID**: `DEFECT-001` (also cataloged as `G02`)
- **Severity**: P1 (High - Platform Reliability / Transport Crash)
- **Target Revision**: `b5caa40bd41848420c4323d22ab648847cdc6745` (Head of PR #9)
- **Affected Component**: `backend/app/mcp/external_adapter.py`
- **Category**: `DEP` / `MCP` (Platform Environment & MCP Transport)
- **Status**: Triaged / Ready for Implementation

---

## 1. Description & Summary

When running PatchDIFF as an MCP server over stdio on Windows, Python defaults standard input (`sys.stdin`) and standard output (`sys.stdout`) streams to the system ANSI code page (typically `cp1252` or `windows-1252` on Western Windows installations). 

When any tool response or error message contains characters outside the 8-bit ANSI repertoire—such as emojis (`🌟✨🚀`), accented Unicode characters, or CJK text (e.g., target fixture T3 `notes.txt`)—the stdio serialization layer fails with:

```text
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f31f' in position 142: character maps to <undefined>
```

Because this exception is unhandled within `external_adapter.py`, the Python process crashes immediately without emitting a valid JSON-RPC response envelope. The host orchestrator (Antigravity, Claude Desktop, or custom MCP client) observes an abrupt transport drop (`exit status 0xffffffff` or `BrokenPipeError`).

---

## 2. Trigger & Reproduction Steps

### Environment
- **Operating System**: Microsoft Windows 11 Pro / Enterprise
- **Python**: 3.12 (standard Windows installer without `PYTHONUTF8=1` in system-wide environment)
- **Session Transport**: Stdio MCP adapter (`python -m app.mcp.external_adapter`)
- **Environment**: Neither `PYTHONIOENCODING=utf-8` nor `PYTHONUTF8=1` set in the MCP client config.

### Reproduction Workflow
1. Initialize a target file containing non-BMP Unicode characters:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "method": "tools/call",
     "params": {
       "name": "patchdiff_initialize_target",
       "arguments": {
         "filename": "unicode_test.txt",
         "content": "# Test Document 🌟\nLine 1: UTF-8 characters: 🚀\nLine 2: CJK: 这是一个测试\n",
         "content_type": "text/markdown"
       }
     }
   }
   ```
2. Call `patchdiff_read_target` to read back the target:
   ```json
   {
     "jsonrpc": "2.0",
     "id": 2,
     "method": "tools/call",
     "params": {
       "name": "patchdiff_read_target",
       "arguments": {
         "target_file_id": "<target_id>",
         "start": 0,
         "length": 100
       }
     }
   }
   ```

### Observed Output
Process terminates with exit code 1. `sys.stderr` log captures:
```text
Traceback (most recent call last):
  File "C:\Python312\Lib\runpy.py", line 198, in _run_module_as_main
  ...
  File "backend\app\mcp\external_adapter.py", line 145, in main
    sys.stdout.write(json.dumps(response) + "\n")
  File "C:\Python312\Lib\encodings\cp1252.py", line 19, in encode
    return codecs.charmap_encode(input,self.errors,encoding_table)[0]
UnicodeEncodeError: 'charmap' codec can't encode character '\U0001f31f' in position 45: character maps to <undefined>
```

---

## 3. Impact Assessment

1. **Host-Agent Disconnection**: Any read, search, or transaction failure that cites non-BMP text (including rejection diagnostics quoting the target's original content) causes an unrecoverable process crash.
2. **Silent Failure in Automated Hosts**: When the stdio process dies, MCP clients fail to receive an error code, interpreting the crash as a dead subprocess or host-level infrastructure failure.
3. **Platform Asymmetry**: The server passes all tests on Linux CI (where UTF-8 is standard for stdio) but fails on out-of-the-box Windows developer environments.

---

## 4. Root Cause Analysis

In standard Python on Windows:
- `sys.stdin.encoding` and `sys.stdout.encoding` default to `locale.getpreferredencoding()`, which resolves to `cp1252` on US/Western European Windows systems.
- While the internal PatchDIFF runtime correctly enforces canonical UTF-8 text representations in Postgres and Python strings, `backend/app/mcp/external_adapter.py` relied on Python's implicit stdout stream encoding when writing JSON-RPC strings to `sys.stdout`.
- The MCP specification mandates UTF-8 encoding across stdio and HTTP transports.

---

## 5. Required Remediation

In `backend/app/mcp/external_adapter.py`, configure the standard streams to UTF-8 at process startup before entering the event loop:

```python
import sys

def configure_stdio_utf8() -> None:
    """Ensure stdio streams use UTF-8 regardless of platform default locale."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```

Invoke `configure_stdio_utf8()` in the module entrypoint of `external_adapter.py`.

### Architectural Invariant Check
- **Zero Schema Changes**: Does not touch Postgres migrations, data models, or stored hashes.
- **Pure Transport Fix**: Modifies only the MCP transport adapter layer. Core deterministic runtime remains pure and isolated.
- **Specification Compliance**: Fully aligns with MCP specification requirements for UTF-8 JSON-RPC transport.

---

## 6. Verification & Acceptance Criteria

1. **Unit / Integration Regression Test**:
   - Add a test in `backend/tests/integration/test_external_mcp_e2e.py` that launches `external_adapter.py` as a subprocess without `PYTHONIOENCODING` or `PYTHONUTF8` set.
   - Send `patchdiff_initialize_target` with emoji (`🌟🚀`) and CJK characters.
   - Verify that the process completes with exit code 0 and emits clean, valid JSON-RPC responses over stdout.
2. **Live Platform Verification**:
   - Run the stdio verification suite natively on Windows without `PYTHONIOENCODING=utf-8` in the environment.
   - Verify that all emoji, CJK, and accented read/edit workflows succeed.
