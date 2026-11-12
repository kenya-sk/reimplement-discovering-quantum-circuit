# dqi-reed-solomon

## Operation

Regard an error word $e\in\mathrm{GF}(2^{12})^{4095}$ as the polynomial
$e(z)=\sum_{j=0}^{4094}e_jz^j$. Its 70-symbol syndrome consists of the
evaluations

$$
S_i=e(\gamma^i)=\sum_{j=0}^{4094}e_j\gamma^{ij},
\qquad i=1,\ldots,70.
$$

There is no evaluation at the zeroth power. Tested errors have symbol
weight at most $35=n/2$. The syndrome map defines a
$[4095,4025,71]_{2^{12}}$ Reed–Solomon code, so these 70 symbols determine
every such error uniquely.

For $s=(S_1,\ldots,S_{70})$, the circuit implements

$$
|s\rangle\longmapsto(-1)^{\langle c,e\rangle}|s\rangle,
$$

where $c$ is a fixed 49140-bit vector, the mask. The inner product is
binary: symbol $e_j$ occupies bits $12j$ through $12j+11$ of the packed
error word. The sign is a global phase for one basis state. It varies
with $s$, so it is a relative phase on a superposition.

| register | width | meaning | required final value |
|---|---:|---|---|
| `s[0]` … `s[69]` | 12 qubits each (840 total) | Syndrome symbol $S_{r+1}$ in register $r$ | Unchanged, with phase $(-1)^{\langle c,e\rangle}$ |

The schema declares the registers in order from `s[0]` through `s[69]`.
There is no output register.


## Specification

### 3.1 Data representation

The field is

$$
\mathrm{GF}(2^{12})
=
\mathrm{GF}(2)[x]/(x^{12}+x^7+x^6+x^5+x^3+x+1).
$$

The modulus has integer representation 4331 and is the primitive default
polynomial used by the `galois` package. Integers from 0 through 4095
encode the field elements: bit $t$ is the coefficient of $x^t$. The
primitive element is $\gamma=x$, represented by integer 2.

Register `s[r]` holds $S_{r+1}$. Within that register, qubit $t$ holds the
coefficient of $x^t$. The binary word paired with $c$ packs each error symbol in the
same little-endian coefficient order.

### 3.2 Task instance

The 4095 error positions correspond in order to
$\gamma^0,\gamma^1,\ldots,\gamma^{4094}$, which enumerate the nonzero field
elements. The syndrome uses the next 70 powers, from $\gamma^1$ through
$\gamma^{70}$.

Counter-mode SHA-256 generates the phase mask $c$. The tag is a fixed
byte string that defines the instance; its text carries no meaning:

```text
c = SHA-256(tag ‖ le32(0)) ‖ SHA-256(tag ‖ le32(1)) ‖ …
tag = b"kickmix/rs-decode-4095/fixup-c/v1"
```

The generator truncates the stream to 6143 bytes and packs it little-endian
into 49140 bits. Bit $k$ of $c$ is bit $k\bmod 8$ of byte $\lfloor k/8\rfloor$; the
top four bits of the final byte are unused. The stream digest is
`8fcd44e5a419ea29d84bb443d75f10dc9ac85dde2085b7851d92cd198eb3785a`,
and the mask has popcount 24492.

The 840-by-49140 binary syndrome matrix has full row rank 840. The fixed
mask lies outside its row space. Consequently, no linear parity of the supplied syndrome bits can replace
$\langle c,e\rangle$; the phase requires decoding or an equivalent nonlinear computation.

### 3.3 Correctness and examples

The circuit must be correct on the syndromes of errors of symbol weight
at most 35. Testing does not exercise other 840-bit inputs. For an
in-domain input, the circuit must preserve every syndrome qubit and apply
exactly the sign $(-1)^{\langle c,e\rangle}$. It must also return every
workspace qubit to zero before freeing it. Section 6 describes the failure
allowance.

Three fixed test cases make the encodings concrete:

- For $e=0$, all syndrome registers hold 0 and the required sign is $+1$.
- For $e_0=1$ with every other symbol zero, $S_i=1$ for all $i$. Bit 0 of
  $c$ is 0, so the required sign is $+1$.
- For $e_{2047}=2049$, the symbol has bits 0 and 11 set. Its contribution
  is therefore the parity of mask bits 24564 and 24575. Those bits are 0
  and 1, so the required sign is $-1$.


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
