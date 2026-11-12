"""Container-only circuit builder. Its stdout transports op bytes, not a verdict."""

import gc
import os
import runpy
import shutil
import stat
import sys
from pathlib import Path


def main() -> None:
    source = sys.argv[1]
    # Preserve a binary transport before routing the candidate's ordinary output
    # to the log. Anything written to the transport is independently validated.
    sys.stdout.flush()
    transport = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    ops = Path("/tmp/circuit.ops")
    os.environ["UNCOMPUTE_OPS_PATH"] = str(ops)
    sys.argv[:] = [source]
    gc.disable()
    runpy.run_path(source, run_name="__main__")
    if not stat.S_ISREG(ops.lstat().st_mode):
        raise ValueError("Circuit output must be a regular op-stream file")
    with ops.open("rb") as stream, os.fdopen(transport, "wb") as output:
        shutil.copyfileobj(stream, output, 1 << 20)


if __name__ == "__main__":
    main()
