# dqi-hermitian

## Operation

Let $H$ be the fixed $123\times512$ parity-check matrix defined under the
task instance, and let $c$ be the fixed 3072-bit mask. For every error
$e\in\mathrm{GF}(64)^{512}$ of symbol weight at most 47, the circuit must act
on its syndrome $s=He$ as

$$
\lvert s\rangle\longmapsto
(-1)^{\langle c,e\rangle_2}\lvert s\rangle.
$$

Here $\langle c,e\rangle_2$ is the binary inner product of $c$ with the
3072-bit expansion of $e$. Symbol $e_i$ occupies bits $6i$ through $6i+5$.
The designed-distance guarantee ensures that at most one error of weight at
most 47 has a given syndrome. The required sign therefore depends only on
the input registers.

| register | width | meaning | required final value |
|---|---:|---|---|
| $s_0,\ldots,s_{122}$ | 6 qubits each | Syndrome symbol $s_r\in\mathrm{GF}(64)$ | Unchanged |

The registers follow parity-check-row order, for 738 input qubits in
total. There is no output register: the result is solely the relative
phase applied to each computational-basis branch. Any decoded-error data
must be temporary.


## Specification

### 3.1 Data representation

- The field is
  $\mathrm{GF}(64)=\mathrm{GF}(2)[x]/(x^6+x^4+x^3+x+1)$. Elements are
  integers from 0 through 63 in the polynomial basis, with bit $t$ equal to
  the coefficient of $x^t$. This modulus is the `galois` library default,
  and the residue class of $x$ is primitive.
- Each syndrome register is little-endian: qubit $t$ of register $s_r$
  carries the coefficient of $x^t$ in that field element.
- The error word contains 512 symbols in the same basis. Symbol $e_i$ maps
  to mask bits $6i$ through $6i+5$, and the phase exponent is their binary
  inner product with $c$.

### 3.2 Task instance

The code lives on the genus-$28$ Hermitian curve

$$
y^8+y=x^9
$$

over $\mathrm{GF}(64)$. Its 512 affine rational points follow lexicographic
order as integer pairs $(x,y)$, with $x$ as the major key and $(0,0)$
first.

At the curve's point at infinity, $x$ and $y$ have pole orders 8 and 9.
Consequently, the monomial $x^ay^b$ has pole order $8a+9b$. The rows of $H$
are the 123 monomials satisfying

$$
0\le b\le7,\qquad 8a+9b\le150,
$$

ordered first by $b$ and then by $a$, and evaluated at the 512 affine
points. Restricting $b$ to this range loses nothing because the curve
equation reduces every occurrence of $y^8$.

The kernel of $H$ is a $[512,389]$ code. Its designed minimum distance obeys

$$
d\ge150-2(28)+2=96,
$$

so syndromes uniquely identify errors through symbol weight

$$
\left\lfloor\frac{96-1}{2}\right\rfloor=47.
$$

These are precisely the in-domain inputs. The circuit may implement any
reversible behavior on syndromes that have no such error.

Counter-mode SHA-256 generates the fixed mask $c$, with the fixed
instance tag `b"kickmix/hopi-512/fixup-c/v1"` and a little-endian 32-bit
counter. The tag is a fixed byte string; its text carries no meaning. The
generator truncates the stream to 384 bytes and packs it little-endian into
3072 bits. Bit $k$
of $c$ is bit $k\bmod8$ of byte $\lfloor k/8\rfloor$. There are no unused
trailing bits. The stream's SHA-256 digest is:

`10fe6addc16595734e774145bfb571af2f11870903306a5f047aaebd8a7b3181`

The mask has 1,545 set bits and lies outside the binary row space of the
bit-expanded parity-check matrix. Thus no linear function of the supplied
syndrome reproduces its phase. The executable
[classical oracle](reference.py) reconstructs the curve, matrix, mask, and
required sign.

### 3.3 Correctness and examples

A tested input is correct exactly when all 123 syndrome registers finish
with their initial values and the branch acquires
$(-1)^{\langle c,e\rangle_2}$. The evaluator checks register restoration and the
sign exactly; section 6 describes the failure allowance.

Every evaluation includes the following four fixed examples, recomputed
against the classical oracle:

| test error $e$ | syndrome $s$ | sign |
|---|---|---:|
| Zero | All 123 symbols 0 | $+1$ |
| Value 1 at point $(0,0)$ | $s_0=1$, all other symbols 0 | $-1$ |
| Value 42 at point $(17,15)$ | All 123 symbols nonzero: $s_0=42$, $s_1=9$, $s_2=47,\ldots$ | $+1$ |
| Value 63 at point $(63,61)$ | All 123 symbols nonzero: $s_0=63$, $s_1=8$, $s_2=34,\ldots$ | $-1$ |

In general, an error of value $v$ at a single point $P$ gives

$$
s_r=v\,m_r(P),
$$

where $m_r$ is the monomial defining row $r$. At $(0,0)$ every listed
monomial except the constant vanishes, explaining why that example has only
one nonzero syndrome symbol. Its sign is negative because bit 0 of $c$
equals 1.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
