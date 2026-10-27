"""Non-model preparation only. This program cannot launch comparative agents."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate_inputs(manifest: dict, root: Path = ROOT) -> list[str]:
    errors = []
    for study in manifest["studies"].values():
        for artifact in study["artifacts"]:
            path = (root / artifact["path"]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f"Missing or invalid artifact: {artifact['path']}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                errors.append(f"SHA-256 mismatch: {artifact['path']}")
    return errors


def stage(manifest: dict, study_name: str, destination: Path) -> dict:
    study = manifest["studies"][study_name]
    fixtures = [item for item in study["artifacts"] if item["role"] == "fixture"]
    if not fixtures:
        raise ValueError(f"{study_name}: no authenticated original fixtures are available")
    destination.mkdir(parents=True, exist_ok=False)
    for arm in "ABC":
        arm_dir = destination / arm
        arm_dir.mkdir()
        requests = []
        for artifact in fixtures:
            source = ROOT / artifact["path"]
            shutil.copyfile(source, arm_dir / source.name)
            if arm != "A":
                content_type = {".py": "text/x-python", ".json": "application/json", ".md": "text/markdown"}[source.suffix]
                requests.append({"tool": "patchdiff_initialize_target", "arguments": {
                    "filename": source.name, "content": source.read_bytes().decode("utf-8"), "content_type": content_type}})
        if requests:
            (arm_dir / "initialization.jsonl").write_text(
                "".join(json.dumps(request, ensure_ascii=True) + "\n" for request in requests), encoding="utf-8")
        if study.get("task_prompt"):
            shutil.copyfile(ROOT / study["task_prompt"], arm_dir / "TASK.md")
            tool_prompt = next(item for item in study["artifacts"]
                               if item["role"] == "tool_prompt" and item["arm"] == arm)
            shutil.copyfile(ROOT / tool_prompt["path"], arm_dir / "TOOLS.md")
    receipt = {"study": study_name, "gate_2": "closed", "preparation_only": True,
               "model_invocations": 0, "oracle_copied": False, "fixture_hashes": fixtures,
               "database_setup": "B/C initialization.jsonl contains MCP requests; staging executes no transactions"}
    (destination / "preparation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inputs", action="store_true", help="Check committed artifact hashes only")
    parser.add_argument("--stage", choices=["primary", "supplemental"])
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    errors = validate_inputs(manifest)
    if errors:
        print(json.dumps({"status": "invalid_inputs", "errors": errors}))
        return 1
    if args.stage:
        if args.destination is None:
            parser.error("--stage requires --destination (a new directory)")
        try:
            receipt = stage(manifest, args.stage, args.destination)
        except (ValueError, FileExistsError) as exc:
            print(json.dumps({"status": "blocked", "detail": str(exc)}))
            return 2
        print(json.dumps(receipt))
        return 0
    missing = {name: study["missing"] for name, study in manifest["studies"].items() if study["missing"]}
    print(json.dumps({"input_hashes_valid": True, "gate_2": "closed", "missing": missing,
                      "execution_blockers": manifest["execution_blockers"], "model_invocations": 0}, indent=2))
    return 0 if args.check_inputs else 2


if __name__ == "__main__":
    raise SystemExit(main())
