from pathlib import Path
import re


def test_complete_documented_python_json_markdown_batch_examples():
    path = Path(__file__).resolve().parents[3] / "docs/STRUCTURAL_BATCH_EDITING.md"
    blocks = re.findall(r"```python\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 1
    namespace = {}
    exec(compile(blocks[0], str(path), "exec"), namespace)
    assert namespace["python_output"].count("return 200") == 3
    assert namespace["markdown_output"].count("state: ready") == 3
