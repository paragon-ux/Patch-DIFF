from backend.tests.verification.structural_batch.verify import run


def test_frozen_five_file_task_uses_five_atomic_batches_over_real_stdio(tmp_path):
    result = run(tmp_path / "batch")
    assert result["oracle"]["complete_correct"]
    assert len(result["files"]) == 5 and sum(item["group_count"] for item in result["files"]) == 20
    assert result["editing_tools_calls"] == {"patchdiff_observe_scope": 5, "patchdiff_submit_observed_operations": 5,
                                             "patchdiff_save": 5, "patchdiff_replay": 5}
    assert result["model_invocations"] == 0 and result["gate2"] == "closed"
