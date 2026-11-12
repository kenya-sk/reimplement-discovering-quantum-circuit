# coulomb-potential

## Operation

For distinct points $r_i,r_j\in\{0,\ldots,255\}^3$, let $n_2$ denote their
squared distance and let $F(n_2)$ denote the scaled inverse distance:

$$
n_2=\sum_{c\in\{x,y,z\}}(r_{i,c}-r_{j,c})^2,
\qquad
F(n_2)=\operatorname{round}\!\left(\frac{2^{24}}{\sqrt{n_2}}\right).
$$

Rounding selects the nearest integer, with halves rounded away from zero.
The circuit must preserve both points and add $F(n_2)$ into the accumulator
modulo $2^{25}$:

$$
\lvert r_i\rangle\lvert r_j\rangle\lvert k\rangle
\longmapsto
\lvert r_i\rangle\lvert r_j\rangle
\lvert k+F(n_2)\bmod 2^{25}\rangle.
$$

| register | width | meaning | required final value |
|---|---:|---|---|
| `rix` | 8 qubits | $x$ coordinate of $r_i$ | Unchanged |
| `riy` | 8 qubits | $y$ coordinate of $r_i$ | Unchanged |
| `riz` | 8 qubits | $z$ coordinate of $r_i$ | Unchanged |
| `rjx` | 8 qubits | $x$ coordinate of $r_j$ | Unchanged |
| `rjy` | 8 qubits | $y$ coordinate of $r_j$ | Unchanged |
| `rjz` | 8 qubits | $z$ coordinate of $r_j$ | Unchanged |
| `k` | 25 qubits | Modular accumulator | $k+F(n_2)\bmod2^{25}$, within the allowed error |


## Specification

### 3.1 Data representation

All seven registers are little-endian unsigned integers. Coordinate
differences are mathematical signed differences, although each coordinate
register holds an unsigned value. Squaring an unextended two's-complement
bit pattern therefore does not produce the required $n_2$.

The integer $F(n_2)$ represents the inverse distance on a $2^{-24}$
fixed-point grid. The accumulator is an unsigned residue modulo $2^{25}$.
Its initial value is arbitrary, so the circuit must add the result rather
than write or XOR it.

The grader reads accumulator errors as centered modular residues in
$(-2^{24},2^{24}]$. This convention makes the correctness band continuous
across modular wraparound.

### 3.2 Task instance

Each coordinate has eight bits, so both points lie on a $256^3$ grid. Equal
points are outside the domain because the inverse distance is singular. For
distinct points, the squared distance satisfies

$$
1\leq n_2\leq3\cdot255^2=195{,}075.
$$

Exactly 139,637 integers in this interval are sums of three squared
coordinate differences with magnitudes of at most 255. The output scale
makes the largest value, $F(1)=2^{24}$, fit in 25 bits without saturation.
Across the achievable domain, $F$ ranges from 37,986 to 16,777,216.

[reference.py](reference.py) enumerates the achievable values, checks the
ideal table, and documents the fixed instance in executable form.

### 3.3 Correctness and examples

For each tested input, first compute the integer discrepancy

$$
\Delta=(k_{\mathrm{out}}-k_{\mathrm{in}})-F(n_2).
$$

Reduce $\Delta$ modulo $2^{25}$ to its unique representative in the centered
interval $(-2^{24},2^{24}]$. The output is correct when all six coordinate
registers round-trip exactly and the reduced discrepancy obeys

$$
|\Delta|\leq32.
$$

The bound is inclusive: the grader accepts $\Delta=32$ and $\Delta=-32$,
and it rejects $\Delta=33$ and $\Delta=-33$. Each unit of $\Delta$ is one
accumulator least-significant bit, that is, $2^{-24}$ in the inverse
distance. The 32-unit band therefore permits an absolute error of
$32\cdot2^{-24}\approx1.91\times10^{-6}$ in $1/\lVert r_i-r_j\rVert$, below
$2\times10^{-6}$.

The band is the only approximation allowance. The specification prescribes
no intermediate difference, square, sum, or inverse-square-root
representation.

Representative ideal values are:

| $n_2$ | $F(n_2)$ |
|---:|---:|
| 1 | 16,777,216 |
| 2 | 11,863,283 |
| 3 | 9,686,330 |
| 4 | 8,388,608 |
| 5 | 7,502,999 |
| 16,384 | 131,072 |
| 195,075 | 37,986 |

For example, $r_i=(0,0,0)$ and $r_j=(1,0,0)$ give $n_2=1$. With
`k = 20,000,000`, the exact accumulator result is

$$
20{,}000{,}000+16{,}777{,}216\bmod2^{25}=3{,}222{,}784.
$$

The grader accepts any output within 32 centered modular units of that
value, provided all coordinate registers stay unchanged.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
