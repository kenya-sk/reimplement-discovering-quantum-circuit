"""Build actual circuits, evaluate complete trajectories, and compare certified hashes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from qdiscover.artifacts import write_json
from qdiscover.catalog import UPSTREAM_COMMIT, UPSTREAM_ROOT, published_result, task_dir
from qdiscover.process import run_process
from qdiscover.sandbox import SandboxConfig, build_circuit, ensure_available, judge_circuit


def execution_env(task: str, kernel: str = "auto") -> dict[str, str]:
    env = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ
    }
    env["PYTHONPATH"] = os.pathsep.join(
        [str(UPSTREAM_ROOT), str(Path(__file__).resolve().parents[1])]
    )
    env["QDISCOVER_TASK_DIR"] = str(task_dir(task).resolve())
    env["NUMBA_CACHE_DIR"] = str(Path(".cache/numba").resolve())
    if kernel != "auto":
        env["UNCOMPUTE_KERNEL"] = "1" if kernel == "c" else "0"
    return env


@dataclass(frozen=True)
class Evaluation:
    task: str
    valid: bool
    report: dict[str, Any]
    source_sha256: str
    diagnostic: bool
    elapsed_s: float
    error: str | None = None
    sandbox: dict[str, Any] = field(default_factory=dict)

    @property
    def metrics(self) -> dict[str, Any]:
        return self.report.get("metrics", {})

    @property
    def cost(self) -> int | None:
        cost = self.metrics.get("tq_cost")
        return cost if self.valid and isinstance(cost, int) and cost >= 0 else None


def evaluate(
    task: str,
    source: Path,
    out: Path,
    *,
    timeout: float = 3600,
    jobs: int = 1,
    shots: int | None = None,
    kernel: str = "auto",
    sandbox: SandboxConfig | None = None,
) -> Evaluation:
    if jobs < 1 or kernel not in {"auto", "c", "python"}:
        raise ValueError("Invalid jobs or kernel")
    source, out = source.resolve(), out.resolve()
    config = sandbox or SandboxConfig()
    execution = ensure_available(config)
    out.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    env = execution_env(task, kernel)
    start = time.monotonic()
    report: dict[str, Any] = {}
    error = None
    # Clear previous results before any build, so failed reruns cannot reuse stale verdicts.
    for name in ("report.json", "tq_cost.json", "evaluation.json", "container-report.json"):
        (out / name).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="qdiscover-ops-") as temp:
        ops = Path(temp) / "circuit.ops"
        if config.mode == "docker":
            build = build_circuit(
                config, execution["image_id"], task, source, ops, timeout=timeout, kernel=kernel
            )
        else:
            env["UNCOMPUTE_OPS_PATH"] = str(ops)
            shim = (
                "import gc,runpy,sys; gc.disable(); "
                "p=sys.argv[1]; sys.argv[:]=[p]; runpy.run_path(p,run_name='__main__')"
            )
            build = run_process(
                [sys.executable, "-c", shim, str(source)],
                cwd=UPSTREAM_ROOT,
                env=env,
                timeout=timeout,
            )
        (out / "build.stdout.log").write_text(build.stdout)
        (out / "build.stderr.log").write_text(build.stderr)
        remaining = timeout - (time.monotonic() - start)
        if build.output_limited:
            error = "build/output-limit"
        elif build.returncode or not ops.is_file():
            error = "build/timeout" if build.timed_out else "build/failed"
        elif remaining <= 0:
            error = "evaluate/timeout"
        else:
            if config.mode == "docker":
                result = judge_circuit(
                    config,
                    execution["image_id"],
                    task,
                    ops,
                    out,
                    timeout=remaining,
                    kernel=kernel,
                    jobs=jobs,
                    shots=shots,
                )
                if not result.timed_out and not result.output_limited and result.stdout.strip():
                    try:
                        report = json.loads(result.stdout)
                    except json.JSONDecodeError:
                        error = "evaluate/invalid-report"
                    else:
                        write_json(out / "report.json", report)
                        if report.get("verdict") == "OK":
                            metrics = report["metrics"]
                            write_json(
                                out / "tq_cost.json",
                                {
                                    "tq_cost": metrics["tq_cost"],
                                    "metrics": {
                                        "toffoli": math.floor(metrics["toffoli"]),
                                        "qubits": metrics["qubits"],
                                    },
                                },
                            )
            else:
                command = [
                    sys.executable,
                    "-m",
                    "qdiscover.worker",
                    "--task-dir",
                    str(task_dir(task).resolve()),
                    "--ops",
                    str(ops),
                    "--out",
                    str(out),
                    "--jobs",
                    str(jobs),
                ]
                if shots is not None:
                    command += ["--shots", str(shots)]
                result = run_process(command, cwd=UPSTREAM_ROOT, env=env, timeout=remaining)
                if (out / "report.json").is_file():
                    report = json.loads((out / "report.json").read_text())
            (out / "evaluate.stdout.log").write_text(result.stdout)
            (out / "evaluate.stderr.log").write_text(result.stderr)
            if result.output_limited:
                error = "evaluate/output-limit"
            elif result.timed_out:
                error = "evaluate/timeout"
            elif result.returncode:
                error = (report.get("fail") or {}).get("code", "evaluate/failed")
            elif error is None and report.get("verdict") != "OK":
                error = "evaluate/missing-verdict"
    evaluation = Evaluation(
        task,
        error is None and report.get("verdict") == "OK",
        report,
        source_hash,
        shots is not None,
        time.monotonic() - start,
        error,
        execution,
    )
    write_json(out / "evaluation.json", asdict(evaluation))
    return evaluation


def compare_published(result: Evaluation, variant: str) -> dict[str, Any]:
    expected = published_result(result.task, variant)
    metrics = result.metrics
    comparisons = {
        key: metrics.get(key) == getattr(expected, key) for key in ("toffoli", "qubits", "tq_cost")
    }
    comparisons["h_ops"] = result.report.get("h_ops") == expected.h_ops
    return {
        "task": result.task,
        "variant": variant,
        "valid": result.valid,
        "diagnostic": result.diagnostic,
        "reproduced": result.valid and not result.diagnostic and all(comparisons.values()),
        "matches": comparisons,
        "measured": metrics,
        "expected": asdict(expected),
        "error": result.error,
        "upstream_commit": UPSTREAM_COMMIT,
    }


def build_kernel() -> str:
    result = run_process(
        ["make", "kernel", f"PYTHON={sys.executable}"],
        cwd=UPSTREAM_ROOT,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()
