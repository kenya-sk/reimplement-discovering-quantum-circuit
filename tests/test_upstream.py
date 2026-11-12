import subprocess
from pathlib import Path

import pytest

from qdiscover.catalog import TASKS, circuit_path, published_result
from qdiscover.upstream import apply_upstream_patch


def test_upstream_patch_application_is_idempotent(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    source = tmp_path / "source.txt"
    source.write_text("before\n")
    patch = tmp_path / "change.patch"
    patch.write_text("--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-before\n+after\n")
    apply_upstream_patch(tmp_path, patch)
    assert source.read_text() == "after\n"
    apply_upstream_patch(tmp_path, patch)
    assert source.read_text() == "after\n"


def test_all_eight_tasks_have_runnable_sources_and_exact_records() -> None:
    assert len(TASKS) == 8
    for task in TASKS:
        for variant in ("discovered", "baseline"):
            assert circuit_path(task, variant).is_file()
            expected = published_result(task, variant)
            assert expected.tq_cost == expected.toffoli * expected.qubits
            assert len(expected.h_ops) == 64


def test_path_traversal_is_rejected() -> None:
    with pytest.raises(ValueError):
        circuit_path("gaussian", "../../anything")
