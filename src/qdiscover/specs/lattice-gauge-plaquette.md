# lattice-gauge-plaquette

## Operation

A lattice-gauge configuration assigns a group element to each directed link.
It describes parallel transport along that link; traversal in the opposite
direction contributes its inverse. Because the group is nonabelian, factor
order matters in the product around a closed path, called a Wilson loop.

Changing the local frame conjugates a closed-loop product, leaving its trace
unchanged. Reversing the loop replaces the product by its inverse. Since
$SU(3)$ matrices are unitary, this complex-conjugates the trace, so its real
part is also orientation-independent. Define

$$
S_P=\sum_{192\ \mathrm{plaquettes}} f(P),\qquad
S_R=\sum_{384\ \mathrm{rectangles}} f(R),\qquad
f(g)=2\,\mathrm{Re}\,\mathrm{tr}(M_g).
$$

The circuit implements

$$
\lvert g_0\cdots g_{191}\rangle\lvert k\rangle
\longmapsto
\lvert g_0\cdots g_{191}\rangle
\lvert k+a_P S_P+a_R S_R\bmod 2^{51}\rangle.
$$

| register | width | meaning | required final value |
|---|---:|---|---|
| `g0` … `g191` | 9 qubits each | Link group elements | Unchanged |
| `k` | 51 qubits | Modular accumulator | $k+a_PS_P+a_RS_R\bmod 2^{51}$ exactly |

Sites use $s=x+4y+16z$. The link from site $s$ in direction
$\mu\in\{0,1,2\}$ has index $\ell=3s+\mu$. The registers come in
increasing $\ell$ order, then `k`.


## Specification

### 3.1 Data representation

The finite subgroup $G=\Sigma(72\times3)\subset SU(3)$ of order 216 replaces
the continuous link domain. This gives each link a finite
basis while retaining nonabelian multiplication, inverses, and the defining
matrix trace.

In the encoding of Osorio Perez et al. (2025), arXiv:2511.17437, every
element has the unique normal form

$$
g=\omega^p C^q E^r V^{2s+t}X^u,
$$

where $p$, $q$, and $r$ are three-valued exponents and $s$, $t$, and $u$
are binary. These coordinates specify a unique ordered generator product
despite the generators not commuting. The nine-bit encoding is

$$
\lvert u\,t\,s\,r_1r_0\,q_1q_0\,p_1p_0\rangle.
$$

There are 216 valid codes among 512 bit patterns, and code `0` is the
identity. Invalid patterns are outside the input promise.

Conjugating an element does not change its trace, so
$f(hgh^{-1})=f(g)$ and $f$ is a class function. It also satisfies
$f(g^{-1})=f(g)$. Its exact values and multiplicities are

| $f$ | +6 | −3 | −2 | +1 | 0 | +2 | −1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Elements | 1 | 2 | 9 | 18 | 24 | 54 | 108 |

The value $+6$ occurs only at the identity, while $-3$ occurs at the two
nonidentity central elements. For a uniform group element,

$$
\mathbb E[f]=0,\qquad
\mathbb E[f^2]=\frac{432}{216}=2,\qquad
\mathrm{Var}[f]=2.
$$

Any two distinct loops differ in at least one link. Condition on every link
except one that lies in the first loop and not the second. The second loop
product is fixed, while the first remains uniform because multiplying a fixed
element by a uniform one is uniform. Its conditional mean is therefore zero,
so the covariance vanishes and the variances add:

$$
\sigma(S_P)=\sqrt{192\cdot2}=\sqrt{384}=19.5959\ldots\approx19.6,\qquad
\sigma(S_R)=\sqrt{384\cdot2}=\sqrt{768}=27.7128\ldots\approx27.7.
$$

The full ranges are

$$
S_P\in[-576,1152],\qquad S_R\in[-1152,2304].
$$

The accumulator is an unsigned residue modulo $2^{51}$, with errors expressed
as centered modular residues.

### 3.2 Task instance

The lattice has 64 sites, three positive directions, and 192 links.
Coordinates wrap periodically after four sites in each direction. For
$i<j$, the plaquette product is

$$
P_{ij}(\mathbf x)=
g_i(\mathbf x)\,
g_j(\mathbf x+\hat\imath)\,
g_i(\mathbf x+\hat\jmath)^{-1}\,
g_j(\mathbf x)^{-1}.
$$

The pairs $(0,1)$, $(0,2)$, and $(1,2)$ give 192 plaquettes. For ordered
$i\ne j$, the rectangle product is

$$
R_{ij}(\mathbf x)=
g_i(\mathbf x)\,
g_i(\mathbf x+\hat\imath)\,
g_j(\mathbf x+2\hat\imath)\,
g_i(\mathbf x+\hat\imath+\hat\jmath)^{-1}\,
g_i(\mathbf x+\hat\jmath)^{-1}\,
g_j(\mathbf x)^{-1}.
$$

The ordered pairs allow either direction to be the long side, giving 384
rectangles. Plaquettes use four distinct links with two forward and two
inverse factors; rectangles use six distinct links with three of each.
Every loop closes under the periodic boundaries.
[reference.py](reference.py) defines the complete loop set.

The 51-bit accumulator width follows from the $10^{-8}$ precision target and
resource assumptions of Osorio Perez et al. (2025), with the phase-error
accounting of Kan and Nam (2021), arXiv:2107.12769. The weights encode the
exact physical ratio $-1/20$. The plaquette weight is

$$
a_P=\mathtt{0x8EBA84840FB}=9{,}808{,}233{,}644{,}283.
$$

It is the top 51 bits, most-significant first, of the SHA-256 of the
instance tag `kickmix-plaquette-trace-accumulate-v2`, forced odd. The tag is
a fixed string; its text carries no meaning. The rectangle weight is

$$
a_R=2^{51}-\mathrm{round}(a_P/20)
=\mathtt{0x7FF8DD12F965A}
=2{,}251{,}309{,}402{,}003{,}034.
$$

Rounding is unambiguous because $a_P\bmod20=3$. No rescaling of the Trotter
step puts both loop families on the accumulator's binary grid, because
$2^s/20$ is never an integer for any $s$. The task therefore fixes an odd $a_P$
and an even $a_R$, and the required map has zero numerical tolerance.

### 3.3 Correctness and examples

Define

$$
\Delta=(k_{\mathrm{out}}-k_{\mathrm{in}})
-a_PS_P-a_RS_R\pmod{2^{51}}.
$$

Correctness requires every link to read back exactly and

$$
\Delta=0.
$$

Both the grader and [reference.py](reference.py) reproduce these exact
anchors. Increments use $k_{\mathrm{in}}=0$.

| configuration | $S_P$ | $S_R$ | exact increment |
|---|---:|---:|---:|
| All links identity | 1152 | 2304 | 1,161,977,387,651,968 |
| One link code 9, rest identity | 1128 | 2232 | 961,889,421,308,584 |
| $g_\ell$ = the $(\ell\bmod216)$-th smallest valid code | −100 | 31 | 1,255,773,687,108,314 |

The one-link result is unchanged at links `1`, `47`, `95`, `100`, and `191`.
For the final anchor, $k_{\mathrm{in}}=5$ gives
$k_{\mathrm{out}}=1{,}255{,}773{,}687{,}108{,}319$.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
