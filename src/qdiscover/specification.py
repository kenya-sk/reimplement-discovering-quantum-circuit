"""Task-only model context and the shared algorithm-family response contract."""

import ast
import json
from pathlib import Path
from typing import Any

from qdiscover.catalog import UPSTREAM_ROOT, task_dir

MODEL_RULES = """Construct a Python program using `from uncompute import Builder`.
The evaluator checks outputs, preservation of inputs, phase, clean ancillas,
and distinct gate operands. Minimize T*Q, counting CCX and CCZ as Toffoli.
Measurement outcomes may condition phase corrections, never basis permutations.
The program must emit an op stream with b.emit() honoring UNCOMPUTE_OPS_PATH.
Build with ordinary Python loops; never inspect quantum inputs in Python.
Task resources are available under os.environ['QDISCOVER_TASK_DIR'].
Return self-contained source: do not read any discovered or baseline circuit.
Do not change the grader, contract, or evaluator. No preset implementation is
provided. Query the supplied classical oracle for the required function.
"""


def task_context(task: str) -> dict[str, Any]:
    root = task_dir(task)
    reference = ast.parse((root / "reference.py").read_text())
    return {
        "task": task,
        "circuit_model": MODEL_RULES,
        "contract": json.loads((root / "contract.json").read_text()),
        "specification": (Path(__file__).parent / "specs" / f"{task}.md").read_text(),
        "oracle_functions": [
            {"name": node.name, "arguments": ast.unparse(node.args), "doc": ast.get_docstring(node)}
            for node in reference.body
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
        ],
        "oracle_command": f"qdiscover oracle {task} FUNCTION --args '[...]'",
        "builder_api": (UPSTREAM_ROOT / "uncompute" / "__init__.py").read_text(),
        "api_examples": """b = Builder(); x = b.qubits(3); y = b.qubits(3)
b.qubit_register(x); b.qubit_register(y)
t = b.qubit(); b.ccx(x[0], x[1], t); b.cx(t, y[0])
m = b.hmr(t); b.cz(x[0], x[1], cond=m); b.recycle(t)
b.emit()
Other gates: b.x(q), b.cx(a,b), b.swap(a,b), b.z(q), b.ccz(a,b,c).
Classical input bits are distinct from measurement outcomes:
offset = b.bits(8); b.bit_register(offset)
b.x(x[0], when=offset[0])  # Bit-controlled X; do NOT use cond= here.
b.cx(x[0], y[0], when=offset[1])  # Bit-controlled CX, billed as a Toffoli.
Do NOT pass a Bit as a quantum gate operand, e.g. b.cx(offset[0], x[0]) is invalid.
To copy an input Bit into a clean qubit q, use b.x(q, when=offset[0]); repeat to clear.
Use when= for input Bit controls on x/z/neg/cx/cz.
Use cond= only for Outcome phase corrections on z/cz/neg, as above.
Builder.x(q, when=None) and Builder.cx(ctrl, tgt, when=None) do not accept cond=.
Never condition basis permutations on measurement outcomes.
Ancillas start zero; recycling never replaces uncomputation.
""",
    }


def parse_families(response: dict[str, Any], count: int) -> list[dict[str, str]]:
    families = response.get("families")
    if not isinstance(families, list) or len(families) != count:
        raise ValueError(f"Expected {count} algorithm families")
    if any(
        not isinstance(f, dict)
        or not isinstance(f.get("name"), str)
        or not f["name"].strip()
        or not isinstance(f.get("description"), str)
        for f in families
    ):
        raise ValueError("Each family needs a nonempty name and a description")
    if len({f["name"] for f in families}) != count:
        raise ValueError("Family names must be unique")
    return families
