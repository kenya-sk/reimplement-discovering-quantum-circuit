"""Plain polynomial-basis GF(8) reference, modulus x^3+x+1."""


def multiply(a: int, b: int) -> int:
    result = 0
    for _ in range(3):
        if b & 1:
            result ^= a
        a <<= 1
        if a & 8:
            a ^= 11
        b >>= 1
    return result


def inverse(value: int) -> int:
    if not 0 <= value < 8:
        raise ValueError("GF(8) elements must be three-bit integers")
    if value == 0:
        return 0
    return next(candidate for candidate in range(1, 8) if multiply(value, candidate) == 1)
