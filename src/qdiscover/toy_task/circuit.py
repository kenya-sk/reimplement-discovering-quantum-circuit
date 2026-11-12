"""Known GF(8) circuit proposals for evaluator tests and OpenEvolve smoke runs."""

from __future__ import annotations

from qdiscover.toy_task.reference import inverse


def inverse_circuit(*, anf: bool, mbu: bool = True) -> str:
    lines = [
        "from uncompute import Builder",
        "b = Builder()",
        "x = b.qubits(3)",
        "y = b.qubits(3)",
        "b.qubit_register(x)",
        "b.qubit_register(y)",
    ]

    def monomial(controls: list[int], output: int) -> None:
        if len(controls) == 0:
            lines.append(f"b.x(y[{output}])")
        elif len(controls) == 1:
            lines.append(f"b.cx(x[{controls[0]}], y[{output}])")
        elif len(controls) == 2:
            lines.append(f"b.ccx(x[{controls[0]}], x[{controls[1]}], y[{output}])")
        else:
            a, c, d = controls
            lines.extend(
                ["t = b.qubit()", f"b.ccx(x[{a}], x[{c}], t)", f"b.ccx(t, x[{d}], y[{output}])"]
            )
            if mbu:
                lines.extend(["m = b.hmr(t)", f"b.cz(x[{a}], x[{c}], cond=m)"])
            else:
                lines.append(f"b.ccx(x[{a}], x[{c}], t)")
            lines.append("b.recycle(t)")

    for bit in range(3):
        table = [(inverse(x) >> bit) & 1 for x in range(8)]
        if anf:
            # Boolean Möbius transform: truth table -> algebraic normal form.
            for position in range(3):
                for mask in range(8):
                    if mask & (1 << position):
                        table[mask] ^= table[mask ^ (1 << position)]
            for mask, coefficient in enumerate(table):
                if coefficient:
                    monomial([i for i in range(3) if mask >> i & 1], bit)
        else:
            for value, coefficient in enumerate(table):
                if coefficient:
                    zeros = [i for i in range(3) if not value >> i & 1]
                    lines.extend(f"b.x(x[{i}])" for i in zeros)
                    monomial([0, 1, 2], bit)
                    lines.extend(f"b.x(x[{i}])" for i in reversed(zeros))
    lines.append("b.emit()")
    return "\n".join(lines) + "\n"
