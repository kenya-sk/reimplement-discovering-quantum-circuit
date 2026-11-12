"""Independent integer implementation of paper Eqs. (6), (9), and their inverse.

This validates the branch-recovery invariant. It is not a quantum circuit and
does not assign a Toffoli or qubit count to Python arithmetic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

SECP256K1 = 2**256 - 2**32 - 977


@dataclass(frozen=True)
class State:
    z: int
    f: int
    g: int
    fv: int
    gv: int


def trailing_zeros(value: int) -> int:
    if value == 0:
        raise ValueError("Trailing-zero depth is undefined for zero")
    return (value & -value).bit_length() - 1


def step(state: State) -> State:
    z, f, g, fv, gv = state.z, state.f, state.g, state.fv, state.gv
    if g == 0:
        raise ValueError("Walk has already terminated")
    if g & 1 and z >= 0:
        return State(-z, g, (g - f) // 2, 2 * gv, gv - fv)
    odd = g & 1
    return State(z + 1, f, (g + odd * f) // 2, 2 * fv, gv + odd * fv)


def recover_branch(updated: State) -> tuple[bool, int]:
    """Recover (swap, incoming g parity) using only the updated reachable state."""
    if updated.fv & 3 == 2:
        return True, 1
    if updated.z >= 1:
        return False, 0
    if updated.g == 0:
        return False, 1
    depth = trailing_zeros(updated.fv)
    if depth < 2:
        raise ValueError("State does not satisfy the excursion invariant")
    modulus = 1 << depth
    odd_factor = updated.fv >> depth
    residue = (updated.gv * pow(odd_factor, -1, modulus)) % modulus
    return False, (residue >> (depth - 1)) & 1


def reverse_step(updated: State) -> State:
    swap, parity = recover_branch(updated)
    if swap:
        old_gv = updated.fv // 2
        return State(
            -updated.z,
            updated.f - 2 * updated.g,
            updated.f,
            old_gv - updated.gv,
            old_gv,
        )
    old_fv = updated.fv // 2
    return State(
        updated.z - 1,
        updated.f,
        2 * updated.g - parity * updated.f,
        old_fv,
        updated.gv - parity * old_fv,
    )


@dataclass(frozen=True)
class Walk:
    final: State
    steps: int
    stored_branches: int
    ambiguous_branches: int
    inverse: int


def invert(value: int, prime: int = SECP256K1, *, store_depth: int = 5) -> Walk:
    if prime < 3 or prime % 2 == 0 or not 0 < value < prime:
        raise ValueError("Require odd prime and 0 < value < prime")
    if store_depth < 2:
        raise ValueError("store_depth must be at least 2")
    initial = State(0, prime, value, 0, 1)
    state = initial
    steps = stored = ambiguous = 0
    while state.g:
        updated = step(state)
        actual_branch = (bool(state.z >= 0 and state.g & 1), state.g & 1)
        if recover_branch(updated) != actual_branch or reverse_step(updated) != state:
            raise ArithmeticError("Branch reconstruction failed")
        swap, _ = actual_branch
        if not swap and updated.z <= 0 and updated.g != 0:
            ambiguous += 1
            stored += trailing_zeros(updated.fv) >= store_depth
        state = updated
        steps += 1
        if steps > 4 * prime.bit_length() + 16:
            raise ArithmeticError("Walk exceeded the reference implementation's safety limit")
    if abs(state.f) != 1:
        raise ValueError("Input is not invertible; the modulus must be prime")
    inverse = (state.f * state.fv * pow(2, -steps, prime)) % prime
    if inverse * value % prime != 1:
        raise ArithmeticError("Scaled-coefficient invariant failed")
    # No branch history is used to restore the initial state.
    restored = state
    for _ in range(steps):
        restored = reverse_step(restored)
    if restored != initial:
        raise ArithmeticError("Full walk uncomputation failed")
    return Walk(state, steps, stored, ambiguous, inverse)


def census(samples: int = 1000, seed: int = 0, store_depth: int = 5) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    rng = random.Random(seed)
    walks = [invert(rng.randrange(1, SECP256K1), store_depth=store_depth) for _ in range(samples)]
    stopping = sorted(w.steps for w in walks)
    stored = [w.stored_branches for w in walks]
    ambiguous = sum(w.ambiguous_branches for w in walks)
    return {
        "kind": "classical-invariant-census",
        "samples": samples,
        "seed": seed,
        "store_depth": store_depth,
        "all_inverses_and_reverse_walks_valid": True,
        "stopping_steps": {
            "min": stopping[0],
            "median": stopping[len(stopping) // 2],
            "max": stopping[-1],
        },
        "mean_stored_branches": sum(stored) / samples,
        "fraction_ambiguous_stored": sum(stored) / ambiguous if ambiguous else 0,
        "outside_499_533": sum(not 499 <= w.steps <= 533 for w in walks),
        "history_over_60": sum(v > 60 for v in stored),
        "note": "Single-walk empirical counts; no rare-event guarantee or quantum resource count.",
    }
