"""Task names, source selection, and independently recorded upstream results."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

UPSTREAM_COMMIT = "64b5a13aa249f1360846657392e6c66817b26d0f"
UPSTREAM_ROOT = Path(__file__).parent / "_vendor" / "uncompute"
NUMERICAL_TASKS = ("hhl-angle", "coulomb-potential", "gaussian")
BASELINES = {
    "dqi-reed-solomon": "khattar-eea",
    "dqi-hermitian": "sakata-fengrao",
    "hhl-angle": "haner-piecewise",
    "coulomb-potential": "haner-piecewise",
    "gaussian": "haner-piecewise",
    "chemistry-fe2s2": "babbush-composed",
    "lattice-gauge-plaquette": "osorio-composed",
    "modinv-point-add": "luo-eea",
}
TASKS = tuple(BASELINES)


@dataclass(frozen=True)
class PublishedResult:
    task: str
    source: str
    toffoli: int
    qubits: int
    tq_cost: int
    h_ops: str


def task_dir(task: str) -> Path:
    if task == "toy-gf-inverse":
        return Path(__file__).parent / "toy_task"
    if task not in TASKS:
        raise ValueError(f"Unknown task: {task}")
    return UPSTREAM_ROOT / "tasks" / task


def load_task_module(directory: Path, name: str) -> ModuleType:
    path = directory / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"qdiscover_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def circuit_path(task: str, variant: str = "discovered") -> Path:
    root = task_dir(task)
    if variant == "baseline":
        variant = BASELINES[task]
    elif variant == "discovered" and task == "modinv-point-add":
        variant = "divsteps"
    # Only a folder name, never an arbitrary relative path.
    if not variant or Path(variant).name != variant or variant in {".", ".."}:
        raise ValueError("Variant must be a circuit folder name")
    path = root / "circuits" / variant / "circuit.py"
    if not path.is_file():
        raise ValueError(f"Circuit does not exist: {path}")
    return path


def published_result(task: str, variant: str) -> PublishedResult:
    root = task_dir(task)
    source = circuit_path(task, variant).relative_to(root).as_posix()
    for line in (root / "results.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["source"] == source:
            return PublishedResult(
                task, source, row["toffoli"], row["qubits"], row["tq_cost"], row["h_ops"]
            )
    raise ValueError(f"No published result for {task}/{variant}")
