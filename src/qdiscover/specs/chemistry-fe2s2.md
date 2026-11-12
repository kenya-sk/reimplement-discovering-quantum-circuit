# chemistry-fe2s2

## Operation

Qubitization encodes a Hamiltonian $H=\sum_\ell w_\ell P_\ell$ as a block
of a unitary walk operator. Each $P_\ell$ is a Pauli operator. PREPARE
loads the weights $\lvert w_\ell\rvert/\lambda$ into an index register,
with $\lambda=\sum_\ell\lvert w_\ell\rvert$. SELECT applies the signed
Pauli operator that the index names.

A standard PREPARE uses the alias method (Walker (1977),
doi:10.1145/355744.355749; Vose (1991), doi:10.1109/32.92917;
Babbush et al. (2018), arXiv:1805.03662; Berry et al. (2019),
arXiv:1902.02134). Classical preprocessing spreads the probabilities
over $L$ equal buckets, one per term. Bucket $i$ holds term $i$ and one
alternate term $\mathrm{alt}_i$, and a 16-bit threshold
$\mathrm{keep}_i$ sets the split. The circuit draws a bucket $i$ and a
16-bit value $\tau$ uniformly. It selects term $i$ if
$\tau<\mathrm{keep}_i$, and term $\mathrm{alt}_i$ otherwise.

This task is the map $U_{\mathrm{alias}}^\dagger\,\mathrm{SELECT}\,U_{\mathrm{alias}}$.
$U_{\mathrm{alias}}$ computes the selection from $i$ and $\tau$.
SELECT applies the selected term. $U_{\mathrm{alias}}^\dagger$ erases
the selection. The uniform superposition over $i$ and $\tau$, its
reversal, and the walk reflection are not part of the task.

Each table row $\ell$ stores three alias fields:

- $\mathrm{keep}_\ell$, a 16-bit threshold;
- $\mathrm{alt}_\ell$, a 16-bit alternate row index;
- $\theta_\ell$, the coefficient sign bit ($0$ for $w_\ell>0$, $1$ for $w_\ell<0$).

For a row index $i$ and a comparand $\tau$, define

$$
h=[\tau<\mathrm{keep}_i],
\qquad
\mathrm{sel}=\begin{cases}i & h=1,\\ \mathrm{alt}_i & h=0.\end{cases}
$$

The comparison is strict. On a basis state, $X$ flips a bit, $Z$
contributes a sign that the bit sets, and $Y$ does both. For row
$\ell$, let $a_\ell$ mark the qubits where $P_\ell$ has $X$ or $Y$.
Let $z_\ell$ mark the qubits where $P_\ell$ has $Z$ or $Y$. Every
operator in the table has an even number of $Y$ factors, so its phase
is real:

$$
P_\ell\lvert x\rangle
=(-1)^{\eta_\ell\oplus\mathrm{parity}(x\wedge z_\ell)}
\lvert x\oplus a_\ell\rangle,
\qquad
\eta_\ell=\frac{n_Y(P_\ell)\bmod 4}{2}.
$$

The circuit must implement

$$
\lvert i\rangle_{16}\lvert\tau\rangle_{16}\lvert x\rangle_{40}
\longmapsto
(-1)^{\theta_{\mathrm{sel}}\oplus\eta_{\mathrm{sel}}\oplus
\mathrm{parity}(x\wedge z_{\mathrm{sel}})}
\lvert i\rangle\lvert\tau\rangle\lvert x\oplus a_{\mathrm{sel}}\rangle .
$$

$h$ and $\mathrm{sel}$ do not appear in the output. The circuit must
return every register that holds them to zero before the boundary.

| register | width | value | final value |
|---|---:|---|---|
| `i` | 16 qubits | table row index $i$ | unchanged |
| `sigma` | 16 qubits | comparand $\tau$ | unchanged |
| `x` | 40 qubits | system register, one qubit per spin-orbital | $x\oplus a_{\mathrm{sel}}$ |

The code uses other names for some of these quantities. The grader,
the reference, and the circuits call the comparison bit `f` and the
comparand `sigma`. They call the masks $a_\ell$, $z_\ell$, and
$\eta_\ell$ `flip`, `zy`, and `ny2`.


## Specification

### 3.1 Data representation

All registers are little-endian unsigned integers. Each table row is a
34-bit alias word. From the most significant bit down, it packs
$\theta_\ell$ (1 bit), $\theta_{\mathrm{alt}_\ell}$ (1 bit),
$\mathrm{alt}_\ell$ (16 bits), and $\mathrm{keep}_\ell$ (16 bits).
Row $i$ also stores the sign of row $\mathrm{alt}_i$, so one lookup of
row $i$ returns both possible values of $\theta_{\mathrm{sel}}$. Bit
$t$ of a mask refers to system qubit $t$.

### 3.2 Task instance

The Hamiltonian is the (30e,20o) active-space model of the [2Fe-2S]
complex of Li and Chan (2017), doi:10.1021/acs.jctc.7b00270. The
reference reads it from the authors' published FCIDUMP file, stored
here as `data/fcidump.xz` (see [Data files](#data-files)). The 20 spatial
orbitals give 40 interleaved spin-orbitals. The Jordan–Wigner mapping
turns them into 40 qubits. This gives 232,644 non-identity Pauli terms
with coefficient one-norm 137.2599.

The table keeps the terms with $\lvert w_\ell\rvert\ge10^{-4}$ Ha,
following the truncation practice of sparse qubitization (Berry et al.
(2019), arXiv:1902.02134). It keeps $L=41{,}052$ terms with one-norm
$\lambda=133.4650$ (97.2% of the total). The coefficients round to 16
bits of alias precision.

The map is required for every $0\le i<41{,}052$, every $\tau$, and every
40-bit $x$. The index register can hold 24,484 further values. The
grader never tests them, so the circuit may act on them with any
reversible behavior.

Each system qubit is a spin-orbital, and the Hamming weight of $x$ is
the electron count. The active space holds 30 electrons, and the
Hartree–Fock state is `0x3fffffff`. The grader draws $x$ from all
$2^{40}$ basis states, so a correct circuit cannot assume a fixed
electron count or parity.

#### Row order and frames

The row order and the alias schedule suit the circuit. Two freedoms make
this possible. A joint permutation of terms, coefficients, and Pauli
operators leaves $H$ unchanged. Many alias tables also give the same
rounded distribution.

A *frame* is a fixed Clifford transformation of the 40 system qubits
that maps one Pauli operator of the table to another. The row order uses
seven commuting frames:

| paper | code | origin | preserves coefficient magnitudes |
|---|---|---|---|
| $\sigma_{\alpha\beta}$ | `F` | exchange of spin-up and spin-down modes | yes |
| $\sigma_{XY}$ | `C` | $X\leftrightarrow Y$ exchange from spin-rotation symmetry | yes |
| $\sigma_{\mathrm{Fe}}$ | `D` | reflection that exchanges the two iron centers | no |
| $\sigma'_{\mathrm{Fe}}$ | `D2` | `D` composed with four orbital-pair swaps | no |
| $\sigma_{\mathrm{thio}}$ | `s_thio` | swap of terminal thiolate orbitals | no |
| $\sigma_{3d}$ | `s_d45` | swap of iron $3d$ orbitals | no |
| $\sigma_{\mu\mathrm{S}}$ | `x_muS` | swap of bridging sulfur orbitals | no |

The spin flip pairs every kept term with a distinct partner of equal
magnitude (20,400 pairs) or maps it to itself (252 terms). The
$X\leftrightarrow Y$ exchange matches 9,942 pair couples into quartets.
The other five frames map Pauli operators exactly where the table uses
them, but their coefficients differ by a few percent.

Rows form 3,221 blocks. A block of rank $k$ spans $2^k$ aligned
addresses, and address bit $p$ of the block switches its $p$-th frame.
Blocks with the same frame set form 14 contiguous regions, and
`contract.json` lists them. Blocks appear in decreasing size, up to
rank 5.

#### Alias schedule

The alias schedule makes nearby rows store identical alias words.
Heavy terms fill the free space of light rows in whole runs of equal
coefficients, so alias words form long constant runs. In the address
range that `F` keys, 18,463 of the 20,374 adjacent row pairs store
identical words. [`reference.py`](reference.py) and
[`alias_sched.py`](alias_sched.py) derive the table from the FCIDUMP
and check every entry.

The table also has these exact properties:

- 820 rows flip no qubit, 23,304 rows flip two, and 16,928 rows flip four.
- Every phase is $\pm1$, because every row has an even number of $Y$ factors.
- Row 40,608 is the only row with $\mathrm{keep}=0$. Its comparison
  always fails, and its alternate is itself.

#### Data files

- `data/fcidump.xz` is the FCIDUMP file `Fe2S2_and_Fe4S4/Fe2S2/fe2s2`
  of github.com/zhendongli2008/Active-space-model-for-Iron-Sulfur-Clusters,
  compressed with xz. `contract.json` pins its SHA-256.
- `data/table.json.xz` holds the 41,052 terms with their coefficients
  and alias words. `reference.py --emit` writes it.
- `data/masks.json.xz` holds the Pauli masks $a_\ell$, $z_\ell$, and
  $\eta_\ell$ of every row.
- `contract.json` holds the derived values that the grader asserts and
  the circuits read, including the 14 frame regions.

### 3.3 Correctness and examples

The map is exact. Section 6 states the conditions that every test shot
must meet. These examples apply the map to three inputs.

Row 0 is $X_{26}Z_{27}Z_{28}X_{29}X_{35}X_{36}$ with
$\mathrm{keep}=8{,}250$, $\mathrm{alt}=36{,}653$, and $\theta=0$. Row
40,608 is $Z_{12}$ with $\mathrm{keep}=0$.

- $i=0$, $\tau=0$, $x=0$: $\tau<8{,}250$, so $h=1$ and
  $\mathrm{sel}=0$. Row 0 flips qubits 26, 29, 35, and 36, so `x`
  ends as `0x1824000000`. The sign is $+1$.
- $i=0$, $\tau=8{,}250$, $x$ all ones: the strict comparison fails,
  so $h=0$ and $\mathrm{sel}=36{,}653$. Row 36,653 is $Z_{35}$. It
  flips nothing, so `x` stays all ones. Bit 35 of $x$ is 1, so the
  sign is $-1$.
- $i=40{,}608$, $\tau=0$, $x=$ `0x1000`: the comparison with
  $\mathrm{keep}=0$ fails, so $h=0$ and $\mathrm{sel}=40{,}608$, the
  row's own alternate. $Z_{12}$ flips nothing, and bit 12 of $x$ is 1,
  so the sign is $-1$.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
