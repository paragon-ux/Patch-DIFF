import pytest
import json

from evaluation.structural_batch import benchmark
from evaluation.structural_batch.benchmark import paired_intervals, percentile95


def test_paired_block_bootstrap_preserves_constant_ratio_and_reproducibility():
    blocks = [[(float(i + 1), 1.02 * (i + 1)) for i in range(10)] for _ in range(20)]
    result = paired_intervals(blocks, resamples=100)
    assert result == paired_intervals(blocks, resamples=100)
    assert result["pairs"] == 200 and result["blocks"] == 20
    assert result["median_ci95"] == pytest.approx([1.02, 1.02])
    assert result["p95_ci95"] == pytest.approx([1.02, 1.02])


def test_nearest_rank_p95_and_invalid_samples():
    assert percentile95(list(range(1, 21))) == 19
    with pytest.raises(ValueError):
        paired_intervals([[(0, 1)]], resamples=2)
    with pytest.raises(ValueError):
        paired_intervals([], resamples=2)


def test_failed_experiment_retains_failure_without_exception_text(tmp_path, monkeypatch):
    def fail(*_):
        raise ValueError("private database credentials must not be logged")
    monkeypatch.setattr(benchmark, "_run_created_directory", fail)
    destination = tmp_path / "new-run"
    with pytest.raises(ValueError):
        benchmark.run(destination, "diagnostic")
    raw = (destination / "failure.json").read_text()
    record = json.loads(raw)
    assert not record["qualified"] and record["fatal_errors"] == 1
    assert record["error_type"] == "ValueError" and "credentials" not in raw


def test_existing_output_is_never_modified(tmp_path):
    existing = tmp_path / "failure.json"
    existing.write_bytes(b"original immutable bytes")
    with pytest.raises(FileExistsError):
        benchmark.run(tmp_path, "diagnostic")
    assert existing.read_bytes() == b"original immutable bytes"
