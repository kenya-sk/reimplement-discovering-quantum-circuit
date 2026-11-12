"""Private evaluation subprocess; uses the pinned authors' normative evaluator."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from qdiscover.catalog import load_task_module


def main() -> int:
    # Imports belong in the worker so the parent never imports grader globals.
    from uncompute.evalcore.protocol import ops_hash, run_task
    from uncompute.evalcore.task import STRICT

    parser = argparse.ArgumentParser()
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--ops", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--shots", type=int)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    task = load_task_module(args.task_dir, "grader").TASK
    if args.shots is not None:
        if args.shots <= 0 or args.shots > task.num_tests:
            parser.error("Diagnostic shots must be between 1 and the official shot count")
        task.num_tests = args.shots
        task.failure_policy = STRICT  # A reduced draw must never inherit a full-run budget.
    output = contextlib.redirect_stdout(sys.stderr) if args.json_only else contextlib.nullcontext()
    with args.ops.open("rb") as stream, output:
        code, report = run_task(
            task,
            str(args.task_dir),
            stream,
            ops_hash(args.ops),
            out_dir=str(args.out),
            stream_path=args.ops,
            emit_json=False,
            batch_shots=8192,
            jobs=args.jobs,
        )
    print(json.dumps(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
