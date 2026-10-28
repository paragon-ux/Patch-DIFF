"""Evaluator-only reference derived from authenticated originals, never submitted output.

Only the byte splices below are authorized. No formatter, JSON serializer or diff
alignment participates in reference construction. Indentation follows the original
surrounding statements; TASK.md permits no alternative representations.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_HASHES = {
    "matrix_kernel.py": "15906b9ab796d45886133a7a2085f1671dd4c6eb0bf359ea689821ad596f3bf0",
    "schema_defs.py": "c0c99a1618d4500d8e016d3150be0c9247c8b0154c046b387885e9c47bf8fc39",
    "validator_engine.py": "1f4b3e1d9052c72d840b9bcda4633744d7960e0d152924b9539419df1e7f5291",
    "routing_manifest.json": "dcd050b53b771e9dca92a52c25bd8012e67917fd4ca149624b92c76ba87a2e89",
    "MIGRATION_RUNBOOK.md": "fc026134e740237e3e4578e5282ebcb829e29281c6d7050964e96efdc850b0ed",
}
TASK_SHA256 = "a41e9a3413d046ab25090287fae118b47736e6908c28876bc363828e3ea68f34"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected(fixtures: Path | None = None) -> dict[str, bytes]:
    fixtures = fixtures or ROOT / "primary/fixtures"
    sources = {name: (fixtures / name).read_bytes() for name in SOURCE_HASHES}
    for name, data in sources.items():
        if sha(data) != SOURCE_HASHES[name]:
            raise ValueError(f"Unauthenticated source: {name}")
    if sha((ROOT / "primary/prompts/TASK.md").read_bytes()) != TASK_SHA256:
        raise ValueError("Unauthenticated primary task")
    changes: dict[str, list[tuple[int, int, bytes]]] = {name: [] for name in sources}

    def splice(name: str, old: str, new: str, bounds: tuple[int, int] | None = None):
        data = sources[name]
        start, end = bounds or (0, len(data))
        needle = old.encode("utf-8")
        if data[start:end].count(needle) != 1:
            raise ValueError(f"Anchor is not unique: {name}: {old!r}")
        pos = data.index(needle, start, end)
        changes[name].append((pos, pos + len(needle), new.encode("utf-8")))

    def symbol(name: str, identity: str) -> tuple[int, int]:
        data = sources[name]
        nodes = [n for n in ast.parse(data).body
                 if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == identity]
        if len(nodes) != 1:
            raise ValueError(f"Missing/duplicate identity: {identity}")
        node = nodes[0]
        lines = data.splitlines(keepends=True)
        return sum(map(len, lines[:node.lineno - 1])), sum(map(len, lines[:node.end_lineno]))

    mk = "matrix_kernel.py"
    # Explicitly enumerate overlapping starts (advance ONE byte, not needle length).
    stream = b'HEADER::SYNC::SYNC::SYNC::SYNC::SYNC::TRAILER'
    if sources[mk].count(stream) != 1:
        raise ValueError("Sync stream anchor is not unique")
    needle = b"::SYNC::SYNC::"
    starts = [i for i in range(len(stream)) if stream.startswith(needle, i)]
    if starts != [6, 12, 18, 24]:
        raise ValueError("Unexpected overlapping sync occurrences")
    pos = sources[mk].index(stream) + starts[1]
    changes[mk].append((pos, pos + len(needle), b"::SYNC::CALIB::"))
    for kernel in (7, 14, 21):
        bounds = symbol(mk, f"execute_tile_kernel_{kernel:02d}")
        splice(mk, "stride_offset = (block_id << 4) + lane_id",
               "stride_offset = (block_id << 5) + (lane_id * 3)", bounds)
        splice(mk, "scaled = cell >> scale_shift",
               "scaled = (cell + (1 << (scale_shift - 1))) >> scale_shift", bounds)
    bounds = symbol(mk, "dispatch_kernel_triad")
    old = '    total_acc = k07["accumulator"] + k14["accumulator"] + k21["accumulator"]\n'
    splice(mk, old, old + '    total_clips = k07["saturation_clips"] + k14["saturation_clips"] + k21["saturation_clips"]\n', bounds)
    old = '        "total_accumulator": total_acc,\n'
    splice(mk, old, old + '        "total_saturation_clips": total_clips,\n', bounds)

    sd = "schema_defs.py"
    old = '    schema_revision: str = "v3"\n'
    splice(sd, old, old + '    idempotency_scope: str = "GLOBAL"\n', symbol(sd, "SettlementEnvelope"))
    bounds = symbol(sd, "serialize_envelope_v3")
    splice(sd, '"epoch_unit": "sec",', '"epoch_unit": "ns",', bounds)
    splice(sd, '"settlement_epoch": env.settlement_epoch_sec,',
           '"settlement_epoch": env.settlement_epoch_sec * 1_000_000_000,', bounds)
    splice(sd, '        "quorum_required": 2,\n',
           '        "quorum_required": 3,\n        "idempotency_scope": env.idempotency_scope,\n', bounds)

    ve = "validator_engine.py"
    splice(ve, 'VALID_SCOPES = ("GLOBAL", "PARTITION")', 'VALID_SCOPES = ("GLOBAL", "PARTITION", "TENANT")')
    for rule in (4, 11, 19, 27):
        bounds = symbol(ve, f"evaluate_settlement_rule_{rule:02d}")
        for old, new in [
            ('unit = packet.get("epoch_unit", "sec")', 'unit = packet.get("epoch_unit", "ns")'),
            ('max_drift = 30', 'max_drift = 30_000_000_000'),
            ('quorum = int(packet.get("quorum_required", 2))', 'quorum = int(packet.get("quorum_required", 3))'),
            ('if unit != "sec":', 'if unit != "ns":'), ('if quorum < 2:', 'if quorum < 3:'),
        ]:
            splice(ve, old, new, bounds)

    rm = "routing_manifest.json"
    splice(rm, '"manifest_version": "2026.10.1"', '"manifest_version": "2026.10.2-v3"')
    for tenant in (6, 13, 18):
        anchor = f'      "tenant_id": "ten_{tenant:03d}",'.encode()
        if sources[rm].count(anchor) != 1:
            raise ValueError("Tenant identity is not unique")
        start = sources[rm].index(anchor)
        end = sources[rm].index(b"\n    }", start)
        bounds = (start, end)
        for old, new in [('"wire_version": "v2",', '"wire_version": "v3",'),
                         ('"epoch_unit": "sec",', '"epoch_unit": "ns",'),
                         ('"max_drift": 30,', '"max_drift": 30000000000,'),
                         ('"quorum_size": 2,', '"quorum_size": 3,'),
                         ('"idempotency_scope": "GLOBAL",', '"idempotency_scope": "TENANT",')]:
            splice(rm, old, new, bounds)

    md = "MIGRATION_RUNBOOK.md"
    for old, new in [
        ('- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION`', '- **Allowed Idempotency Scopes**: `GLOBAL, PARTITION, TENANT`'),
        ('| `CHK-14-C` | Clock skew p99 | `<= 30 sec` | Trigger NTP resync |', '| `CHK-14-C` | Clock skew p99 | `<= 30000000000 ns` | Trigger PTP hardware resync |'),
        ('| `canary-v3` | `v2` | `sec` | `30` | `2` | `GLOBAL` |', '| `canary-v3` | `v3` | `ns` | `30000000000` | `3` | `TENANT` |'),
        ('=======\nwire_version = "v3"\nepoch_unit = "sec"\nquorum_required = 2\n>>>>>>> REPLACE',
         '=======\nwire_version = "v3"\nepoch_unit = "ns"\nquorum_required = 3\n>>>>>>> REPLACE'),
    ]:
        splice(md, old, new)

    result = {}
    for name, data in sources.items():
        ordered = sorted(changes[name])
        previous = 0
        parts = []
        for start, end, replacement in ordered:
            if start < previous:
                raise ValueError(f"Overlapping reference transformations: {name}")
            parts.extend((data[previous:start], replacement))
            previous = end
        parts.append(data[previous:])
        result[name] = b"".join(parts)
    return result


def reference_manifest(reference: dict[str, bytes]) -> dict:
    return {name: {"length": len(data), "sha256": sha(data)} for name, data in sorted(reference.items())}


def compare(workspace: Path) -> dict:
    reference = expected()
    pinned = json.loads((Path(__file__).parent / "reference_hashes.json").read_text())
    if reference_manifest(reference) != pinned:
        raise ValueError("Reference hashes differ from independently reviewable frozen manifest")
    differences = []
    entries = {p.relative_to(workspace).as_posix(): p for p in workspace.rglob("*")}
    for name in sorted(set(entries) | set(reference)):
        path = entries.get(name)
        wanted = reference.get(name)
        if wanted is None or path is None or path.is_symlink() or not path.is_file():
            differences.append({"filename": name, "error": "unexpected_missing_or_nonregular_entry"})
            continue
        actual = path.read_bytes()
        if wanted != actual:
            first = next((i for i, (a, b) in enumerate(zip(wanted, actual)) if a != b), min(len(wanted), len(actual)))
            differences.append({"filename": name, "first_differing_byte": first,
                                "expected_length": len(wanted), "actual_length": len(actual),
                                "expected_sha256": sha(wanted), "actual_sha256": sha(actual),
                                "expected_context_hex": wanted[max(0, first - 24):first + 24].hex(),
                                "actual_context_hex": actual[max(0, first - 24):first + 24].hex()})
    return {"passed": not differences, "differences": differences, "reference": pinned}


def generate(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in expected().items():
        (destination / name).write_bytes(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate-reference", type=Path)
    group.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    if args.generate_reference:
        generate(args.generate_reference)
    else:
        result = compare(args.workspace)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["passed"] else 1)
