"""OpenEvolve evaluator adapter; every score comes from a full circuit evaluation."""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path
from typing import Any

from qdiscover.artifacts import read_tail, write_json
from qdiscover.evaluate import Evaluation
from qdiscover.evaluate import evaluate as evaluate_circuit
from qdiscover.sandbox import SandboxConfig


def evaluate(
    program_path: str,
    *,
    task: str,
    out_dir: str,
    timeout: float = 3600,
    jobs: int = 1,
    kernel: str = "auto",
    sandbox: dict[str, Any] | None = None,
) -> Any:
    """Return raw T/Q features and maximize 1/(1+TQ), rejecting invalid trajectories."""
    attempt = Path(out_dir) / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=True)
    source = attempt / "circuit.py"
    source.write_bytes(Path(program_path).read_bytes())
    try:
        result = evaluate_circuit(
            task,
            source,
            attempt,
            timeout=timeout,
            jobs=jobs,
            kernel=kernel,
            sandbox=SandboxConfig(**(sandbox or {})),
        )
    except (ValueError, OSError, RuntimeError) as exc:
        result = Evaluation(task, False, {}, "", False, 0, str(exc))
    measured = result.metrics
    cost = None if result.diagnostic else result.cost
    valid = cost is not None
    metrics: dict[str, float] = {
        "valid": float(valid),
        "combined_score": 1.0 / (1 + cost) if cost is not None else 0.0,
        "toffoli": float(measured.get("toffoli", 0)),
        "qubits": float(measured.get("qubits", 0)),
        "tq_cost": float(cost or 0),
    }
    artifacts = {
        "verdict": "VALID" if valid else "INVALID",
        "error": result.error or "",
        "report": json.dumps(result.report),
        "evaluation_directory": str(attempt),
    }
    for name in ("build.stderr.log", "evaluate.stderr.log"):
        path = attempt / name
        if path.is_file():
            artifacts[name] = read_tail(path)
    write_json(attempt / "openevolve_score.json", {"metrics": metrics, "artifacts": artifacts})
    result_type = importlib.import_module("openevolve.evaluation_result").EvaluationResult
    return result_type(metrics=metrics, artifacts=artifacts)


def admit_valid(state: Any, candidate: Any, island: int) -> bool:
    """Admit the required blank seed; every generated child must pass evaluation."""
    if getattr(candidate, "parent_id", "not-a-seed") is None and candidate.generation == 0:
        return True
    return candidate.metrics.get("valid") == 1.0
