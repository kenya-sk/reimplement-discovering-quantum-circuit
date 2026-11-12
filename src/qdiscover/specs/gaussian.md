# gaussian

## Operation

The circuit preserves `X` and adds the encoded Gaussian value to an arbitrary
accumulator `k`:

$$
\lvert X\rangle\lvert k\rangle
\longmapsto
\left\lvert X\right\rangle
\left\lvert k+\operatorname{round}\!\left(
2^{32}e^{-(X_s/2^{32})^2}
\right)\bmod 2^{39}\right\rangle,
$$

where $X_s$ is the signed integer that `X` represents.

| register | width | meaning | required final value |
|---|---:|---|---|
| `X` | 39 qubits | Encoded signed input $x$ | Unchanged |
| `k` | 39 qubits | Arbitrary modular accumulator | $k+f(X_s)\pmod{2^{39}}$ |


## Specification

### 3.1 Data representation

Both registers are little-endian. `X` is a 39-bit two's-complement number
with seven integer bits, including the sign, and 32 fractional bits. Its
represented value is $x=X_s/2^{32}$.

The nonnegative addend is

$$
f(X_s)=\operatorname{round}\!\left(2^{32}e^{-x^2}\right),
$$

where rounding is half away from zero. The addend uses the same $2^{32}$
scale as `X`, so one output unit represents $2^{-32}$. The accumulator `k`
is an unsigned residue modulo $2^{39}$, and addition wraps at that modulus.

### 3.2 Task instance

The domain is the half-open interval

$$
-8\le x<8,
$$

equivalently $-8\cdot2^{32}\le X_s<8\cdot2^{32}$. The domain includes
$x=-8$ but excludes $x=8$. It contains exactly $2^{36}$ of the possible
39-bit input patterns.

The maximum addend is $f(0)=2^{32}$. The function is even and
non-increasing in $|x|$. It rounds to zero at $x=-8$ and at the largest
in-domain value $x=8-2^{-32}$.

The format matches the $10^{-7}$ Gaussian accuracy level of Häner,
Roetteler, and Svore (2018). Section 5 derives the register width from
their published resource table.

### 3.3 Correctness and examples

The input register `X` must round-trip bit-exactly. Let $k^\star$ be the
ideal modular sum from section 1, and first form the residue

$$
r=(k_{\mathrm{out}}-k^\star)\bmod 2^{39}.
$$

The error $\delta$ is this residue recentered into $(-2^{38},2^{38}]$: use
$\delta=r$ when $r\le2^{38}$ and $\delta=r-2^{39}$ otherwise. The
recentering prevents modular wraparound from inflating the measured error.

The units are output ULP, where one ULP is $2^{-32}$, the scale of the
addend. The grader accepts a shot only if

$$
|\delta|\le429.
$$

The radius is inclusive. It comes from

$$
\left\lfloor10^{-7}2^{32}\right\rfloor
=\left\lfloor429.4967296\right\rfloor
=429,
$$

the largest integral radius no wider than $10^{-7}$ in the represented
function value. Its real-value size is
$429\cdot2^{-32}\approx9.9884\times10^{-8}$. The grader applies the
condition to every tested shot separately.

These examples give the ideal addend before accumulation:

| represented $x$ | signed integer $X_s$ | ideal addend $f(X_s)$ |
|---:|---:|---:|
| $-8$ | $-8\cdot2^{32}=-34{,}359{,}738{,}368$ | $0$ |
| $-4$ | $-4\cdot2^{32}=-17{,}179{,}869{,}184$ | $483$ |
| $-1$ | $-2^{32}=-4{,}294{,}967{,}296$ | $1{,}580{,}030{,}169$ |
| $0$ | $0$ | $4{,}294{,}967{,}296$ |
| $1$ | $2^{32}=4{,}294{,}967{,}296$ | $1{,}580{,}030{,}169$ |
| $4$ | $4\cdot2^{32}=17{,}179{,}869{,}184$ | $483$ |


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
