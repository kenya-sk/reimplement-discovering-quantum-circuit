# modinv-point-add

## Operation

Each point on the curve is a pair of integers $(x,y)$ that satisfies

$$
y^2\equiv x^3+7\pmod p,\qquad p=2^{256}-2^{32}-977.
$$

Point addition combines two points $P$ and $Q$ into a third point
$R=P+Q$ on the same curve. Geometrically, it draws the line through $P$ and
$Q$, finds the third intersection with the curve, and reflects that point
across the horizontal axis. For the inputs of this task, $Q_x\ne P_x$, and the
slope of the chord is

$$
\lambda\equiv(Q_y-P_y)(Q_x-P_x)^{-1}\pmod p.
$$

The coordinates of the sum are

$$
R_x=\lambda^2-P_x-Q_x\pmod p,
\qquad
R_y=\lambda(P_x-R_x)-P_y\pmod p.
$$

The circuit is a reversible point adder (Proos and Zalka (2003),
arXiv:quant-ph/0301141). It takes a quantum point $P$ and a classically
supplied point $Q$, and it performs

$$
\lvert P\rangle\longmapsto\lvert P+Q\rangle.
$$


## Specification

### 3.1 Data representation

The circuit declares its registers in this order:

| register | width | meaning | required final value |
|---|---:|---|---|
| `target_x` | 256 qubits | input coordinate $P_x$ | $(P+Q)_x$ |
| `target_y` | 256 qubits | input coordinate $P_y$ | $(P+Q)_y$ |
| `offset_x` | 256 bits | addend coordinate $Q_x$ | input only |
| `offset_y` | 256 bits | addend coordinate $Q_y$ | input only |

Each coordinate register holds a little-endian unsigned integer, the
canonical residue modulo $p$. The two `offset` registers are classical bit
inputs with fresh values on every test. They are not constants compiled into
the circuit, so a circuit must be correct for any addend. A circuit may
compute any classical function of $Q$ at no cost.

### 3.2 Task instance

| quantity | value |
|---|---|
| field prime $p$ | `0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffefffffc2f` |
| coefficient $a$ | 0 |
| coefficient $b$ | 7 |
| $G_x$ | `0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798` |
| $G_y$ | `0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8` |
| subgroup order $n$ | `0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141` |

The base point $G$ lies on the curve and generates a subgroup of prime order
$n$. `contract.json` holds the same values, and `grader.py` asserts them at
import.

Each test reads two raw 256-bit little-endian scalars $s$ and $t$ from one
64-byte block of the seeded test stream. The grader reduces them modulo $n$
(modulo bias about $2^{-127}$) and forms

$$
P=[s]G,\qquad Q=[t]G.
$$

$P$ and $Q$ are therefore independent and nearly uniform points of the curve.
The grader skips a draw if either operand is the identity, if $P=Q$, or if
$P=-Q$. These are the cases where the affine formulas are incomplete. Each
exclusion has measure about $2^{-255}$.

### 3.3 Correctness and examples

A test passes only if three conditions hold. Both output registers contain the
exact canonical coordinates of $P+Q$. The global sign is clean. Every ancilla
has returned to $\lvert0\rangle$.

For example, take $P=G$ and $Q=2G$. The required result is $3G$:

| register | input | required output |
|---|---|---|
| `target_x` | `0x79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798` | `0xf9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9` |
| `target_y` | `0x483ada7726a3c4655da4fbfc0e1108a8fd17b448a68554199c47d08ffb10d4b8` | `0x388f7b0f632de8140fe337e62a37f3566500a99934c2231b6cb9fd7584b8e672` |
| `offset_x` | `0xc6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5` | unchanged |
| `offset_y` | `0x1ae168fea63dc339a3c58419466ceaeef7f632653266d0e1236431a950cfe52a` | unchanged |


Task specification extracted from the pinned andigu/uncompute README (Apache-2.0).
