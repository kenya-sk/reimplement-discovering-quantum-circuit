from pathlib import Path

import pytest

from qdiscover.catalog import NUMERICAL_TASKS, circuit_path
from qdiscover.evaluate import compare_published, evaluate
from qdiscover.sandbox import SandboxConfig
from qdiscover.toy_task.circuit import inverse_circuit

pytestmark = pytest.mark.integration
LOCAL = SandboxConfig(mode="local")


@pytest.mark.parametrize("task", NUMERICAL_TASKS)
@pytest.mark.parametrize("variant", ["discovered", "baseline"])
def test_paper_circuits_and_certified_stream_hashes(
    task: str, variant: str, tmp_path: Path
) -> None:
    result = evaluate(task, circuit_path(task, variant), tmp_path, timeout=120, sandbox=LOCAL)
    comparison = compare_published(result, variant)
    assert comparison["reproduced"], result


def test_python_reference_and_c_kernel_agree(tmp_path: Path) -> None:
    from qdiscover.evaluate import build_kernel

    build_kernel()
    results = [
        evaluate(
            "coulomb-potential",
            circuit_path("coulomb-potential"),
            tmp_path / kernel,
            timeout=120,
            kernel=kernel,
            sandbox=LOCAL,
        )
        for kernel in ("python", "c")
    ]
    assert all(r.valid for r in results)
    assert results[0].report["metrics"] == results[1].report["metrics"]
    assert results[0].report["counters"] == results[1].report["counters"]


@pytest.mark.parametrize("defect", ["phase", "dirty", "wrong-output", "alias"])
def test_evaluator_rejects_coherence_and_cleanliness_defects(defect: str, tmp_path: Path) -> None:
    source = inverse_circuit(anf=True)
    if defect == "phase":
        source = source.replace("b.emit()", "b.z(x[0])\nb.emit()")
    elif defect == "dirty":
        source = source.replace("b.emit()", "b.x(b.qubit())\nb.emit()")
    elif defect == "wrong-output":
        source = source.replace("b.emit()", "b.x(y[0])\nb.emit()")
    else:
        source = source.replace("b.emit()", "b.ccx(x[0], x[0], y[0])\nb.emit()")
    path = tmp_path / "defective.py"
    path.write_text(source)
    result = evaluate("toy-gf-inverse", path, tmp_path / "result", timeout=30, sandbox=LOCAL)
    assert not result.valid


def test_diagnostic_run_never_certifies_and_failed_rerun_clears_stale_result(
    tmp_path: Path,
) -> None:
    result = evaluate(
        "coulomb-potential",
        circuit_path("coulomb-potential"),
        tmp_path,
        shots=64,
        timeout=60,
        sandbox=LOCAL,
    )
    assert result.valid and result.diagnostic
    assert not compare_published(result, "discovered")["reproduced"]
    path = tmp_path / "invalid.py"
    path.write_text("raise ValueError('intentional build failure')\n")
    result = evaluate("toy-gf-inverse", path, tmp_path, timeout=30, sandbox=LOCAL)
    assert not result.valid and result.report == {}
    assert not (tmp_path / "report.json").exists()
