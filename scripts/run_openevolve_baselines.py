#!/usr/bin/env python3
"""Run the catalog's eight tasks sequentially with the configured Claude and GPT models."""

import argparse
import runpy
import shlex
import subprocess
from pathlib import Path

MODELS = {
    "claude-haiku-5-5": "haiku55",
    "claude-sonnet-5-5": "sonnet55",
    "gpt-6.1-terra": "terra61",
    "gpt-6-luna": "luna6",
}
EXECUTION = "docker"
N_WORKERS = 3
N_ITERATIONS = 20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root", default="runs", help="Output root (relative to repository root)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    tasks = runpy.run_path(str(root / "src/qdiscover/catalog.py"))["BASELINES"]
    runs = [(task, model, suffix) for task in tasks for model, suffix in MODELS.items()]
    results = []
    for index, (task, model, suffix) in enumerate(runs, 1):
        label = f"{task} / {model}"
        backend = "openai" if model.startswith("gpt-") else "anthropic"
        out = Path(args.out_root) / f"{task}-{suffix}"
        if (root / out / "run_settings.json").exists():
            print(f"[{index}/{len(runs)}] SKIP {label}: existing run at {out}", flush=True)
            results.append((label, "SKIP (existing run)"))
            continue

        command = [
            "uv", "run", "--locked", "--extra", "openevolve",
            "qdiscover", "openevolve", task,
            "--backend", backend,
            "--execution", EXECUTION, "--out", str(out),
            "--workers", str(N_WORKERS), "--iterations", str(N_ITERATIONS), "--model", model,
        ]
        print(f"[{index}/{len(runs)}] {shlex.join(command)}", flush=True)
        if args.dry_run:
            results.append((label, "DRY RUN"))
            continue
        result = subprocess.run(command, cwd=root, check=False)
        results.append((label, "OK" if result.returncode == 0 else f"FAILED ({result.returncode})"))

    print("\nResults (OK means command exit status 0):", flush=True)
    for task, status in results:
        print(f"  {task}: {status}", flush=True)
    return int(any(status.startswith("FAILED") for _, status in results))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
