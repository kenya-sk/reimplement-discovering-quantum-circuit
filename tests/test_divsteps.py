from math import gcd

import pytest

from qdiscover.divsteps import SECP256K1, State, invert, recover_branch, reverse_step, step


@pytest.mark.parametrize("prime", [3, 5, 7, 11, 17, 31, 61, 127, 251])
def test_all_nonzero_inputs_in_small_prime_fields(prime: int) -> None:
    for value in range(1, prime):
        walk = invert(value, prime)
        assert walk.inverse == pow(value, -1, prime)


@pytest.mark.parametrize("value", [1, 2, 3, SECP256K1 // 2, SECP256K1 - 1])
def test_full_size_boundary_inputs(value: int) -> None:
    walk = invert(value)
    assert walk.inverse == pow(value, -1, SECP256K1)
    assert walk.steps <= 590


def test_scaled_coefficients_and_branch_decoder_at_every_step() -> None:
    prime, value = 251, 199
    state = State(0, prime, value, 0, 1)
    count = 0
    seen: set[tuple[bool, int]] = set()
    while state.g:
        assert state.f & 1
        assert state.fv % 2 == 0 and state.gv % 2 == 1
        assert gcd(state.f, state.g) == 1
        assert (state.fv * value - 2**count * state.f) % prime == 0
        assert (state.gv * value - 2**count * state.g) % prime == 0
        updated = step(state)
        expected = (state.z >= 0 and bool(state.g & 1), state.g & 1)
        assert recover_branch(updated) == expected
        assert reverse_step(updated) == state
        seen.add(expected)
        state, count = updated, count + 1
    assert seen == {(True, 1), (False, 1), (False, 0)}


def test_invalid_domain_and_noninvertible_inputs() -> None:
    for value, modulus in [(0, 7), (7, 7), (1, 8), (3, 9)]:
        with pytest.raises(ValueError):
            invert(value, modulus)
