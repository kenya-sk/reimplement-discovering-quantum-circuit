"""The patched native serializer must match the normative Python serializer."""

import io

import pytest

from qdiscover.catalog import UPSTREAM_ROOT


@pytest.mark.parametrize(
    "case", ["oprec", "tuple", "negative-oprec", "negative-tuple", "table", "bit-as-qubit"]
)
@pytest.mark.parametrize("chunk", [32, 1 << 20])
def test_native_side_table_matches_reference(
    monkeypatch: pytest.MonkeyPatch, case: str, chunk: int
) -> None:
    monkeypatch.syspath_prepend(str(UPSTREAM_ROOT))
    from uncompute import Builder, _tapefast, compact
    from uncompute.ops import OpKind

    monkeypatch.setenv("UNCOMPUTE_KERNEL", "1")
    if not _tapefast.enabled():
        pytest.skip("Native kernel is not built")
    monkeypatch.setattr(compact, "_FLAT_CHUNK", chunk)
    b = Builder()
    q = b.qubit()
    b.qubit_register([q])
    bit = b.bit()
    b.bit_register([bit])
    for _ in range(12):
        b.x(q)
    target = -1 if case.startswith("negative") else q
    if case == "bit-as-qubit":
        b.cx(bit, q)
    elif "tuple" in case:
        # Force an ordinary tuple through the side table rather than packed rows.
        b.x(q)
        item = list(b._items[-1])
        item[3] = target
        b._items._objs[len(b._items) - 1] = tuple(item)
        b._items._rows[(len(b._items) - 1) * 9] = 0xFFFFFFFF
    else:
        gate = (99, 0, ()) if case == "table" else None
        b._items.append(compact.OpRec(int(OpKind.X), ((target, ()),), gate=gate, cc=(bit.id, ())))
    for _ in range(12):
        b.x(q)

    def encode(native: bool) -> tuple[bytes, tuple[type, str] | None]:
        monkeypatch.setenv("UNCOMPUTE_KERNEL", "1" if native else "0")
        out = io.BytesIO()
        error = None
        try:
            # Exercise serialization directly: malformed cases are deliberately
            # inserted below Builder's authoring and phase-accounting checks.
            compact.write_compact(b._build_segments(), out)
        except (ValueError, TypeError) as exc:
            error = (type(exc), str(exc))
        # Buffers exported by ctypes must be released even on an encoding error.
        b.x(q)
        del b._items[-1]
        return out.getvalue(), error

    reference = encode(False)
    assert encode(True) == reference
    assert (reference[1] is not None) == (
        case.startswith("negative") or case in {"table", "bit-as-qubit"}
    )
