# hhl-angle

## Operation

The circuit preserves `X` and adds the encoded angle to an arbitrary
accumulator `k`. Define

$$
f(X)=\operatorname{round}\!\left(
2^{32}\arcsin\!\left(\frac{2^{15}}{X}\right)
\right),
$$

where rounding is to the nearest integer with half-integer cases rounded
away from zero. The required reversible map is

$$
\lvert X\rangle\lvert k\rangle
\longmapsto
\lvert X\rangle
\lvert k+f(X)\bmod 2^{33}\rangle.
$$

| register | width | meaning | required final value |
|---|---:|---|---|
| `X` | 21 qubits | Encoded positive input $x=X/2^{16}$ | Unchanged |
| `k` | 33 qubits | Arbitrary modular accumulator | $k+f(X)\pmod{2^{33}}$ |


## Specification

### 3.1 Data representation

Both registers are little-endian. `X` is unsigned and represents
$x=X/2^{16}$. The integer $f(X)$ encodes an angle with 32 fractional bits,
so one output unit is $2^{-32}$ radians.

The accumulator `k` is an unsigned residue modulo $2^{33}$. Its initial
value is arbitrary, and the addition wraps at that modulus.

### 3.2 Task instance

The input domain is

$$
2^{16}\le X\le 2^{21}-1,
$$

which contains 2,031,616 values and represents
$1\le x\le 32-2^{-16}$. With $C=1/2$, the arcsine argument obeys

$$
\frac{C}{x}=\frac{2^{15}}{X}
\in\left(\frac{1}{64},\frac{1}{2}\right].
$$

The largest ideal addend occurs at `X = 65536` and is

$$
\operatorname{round}(2^{32}\pi/6)=2{,}248{,}839{,}617.
$$

The smallest occurs at `X = 2097151` and is 67,111,627. Both extreme
addends fit in the positive range of the 33-bit accumulator.

### 3.3 Correctness and examples

Let $k^\star=(k+f(X))\bmod 2^{33}$ be the ideal accumulator result. Define
the accumulator error as the centered residue

$$
\delta=\operatorname{center}_{2^{33}}(k_{\mathrm{out}}-k^\star).
$$

Here $\operatorname{center}_{2^{33}}$ selects the unique representative in
$(-2^{32},2^{32}]$. Subtraction modulo $2^{33}$ followed by centering gives
the shortest signed distance between two residues. The bound therefore
applies in the same way near the wraparound and away from it.

The grader accepts a shot only when both conditions hold:

- The returned `X` is bit-for-bit equal to the input `X`.
- The returned accumulator satisfies $|\delta|\le 429$ output units.

The accumulator condition is an absolute bound of
$429\cdot 2^{-32}\approx 9.99\times 10^{-8}$ radians on the added angle,
that is, an error below $10^{-7}$ radians. It applies to every shot. There
is no relative-error rule and no allowance for failed shots.

These examples give the ideal addend before accumulation:

| `X` | represented $x$ | ideal addend $f(X)$ |
|---:|---:|---:|
| 65,536 | 1 | 2,248,839,617 |
| 131,072 | 2 | 1,085,253,432 |
| 524,288 | 8 | 268,610,527 |
| 1,048,576 | 16 | 134,239,583 |
| 2,097,151 | $32-2^{-16}$ | 67,111,627 |

For the wraparound case `X = 65536` with initial accumulator $2^{33}-1$, the
ideal result is $2{,}248{,}839{,}616$. The centered-residue rule compares a
returned residue with that wrapped result without a discontinuity at zero.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
