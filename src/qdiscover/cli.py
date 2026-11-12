"""Commands for exact reproduction, diagnostic runs, and OpenEvolve search."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from qdiscover.artifacts import write_json
from qdiscover.catalog import (
    NUMERICAL_TASKS,
    TASKS,
    UPSTREAM_COMMIT,
    circuit_path,
    published_result,
)
from qdiscover.divsteps import census
from qdiscover.evaluate import build_kernel, compare_published, evaluate, execution_env
from qdiscover.process import run_process
from qdiscover.sandbox import DEFAULT_IMAGE, SandboxConfig, build_image
from qdiscover.upstream import setup_upstream


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("upstream-setup", help="initialize the author submodule and local patches")
    commands.add_parser("list", help="print published counts, without claiming measurement")
    commands.add_parser("kernel", help="compile the optional authors' C simulator")
    docker_build = commands.add_parser("docker-build", help="build the isolated evaluation image")
    docker_build.add_argument("--image", default=DEFAULT_IMAGE)
    docker_build.add_argument("--context", type=Path)
    repro = commands.add_parser("reproduce", help="build and evaluate published circuits")
    repro.add_argument("--tasks", nargs="+", default=["numerical"])
    repro.add_argument(
        "--variant", default="both", help="discovered, baseline, both, or a circuit folder name"
    )
    repro.add_argument("--out", type=Path, default=Path("runs/reproduction"))
    _evaluation_options(repro)
    repro.add_argument("--shots", type=int, help="diagnostic only; cannot certify reproduction")
    run = commands.add_parser("evaluate", help="evaluate a new candidate circuit")
    run.add_argument("task", choices=(*TASKS, "toy-gf-inverse"))
    run.add_argument("source", type=Path)
    run.add_argument("--out", type=Path, default=Path("runs/evaluation"))
    _evaluation_options(run)
    oe = commands.add_parser("openevolve", help="search using the actual pinned OpenEvolve engine")
    oe.add_argument("task", choices=(*TASKS, "toy-gf-inverse"))
    oe.add_argument(
        "--backend",
        choices=["anthropic", "openai", "openrouter", "gemini", "compatible"],
        default="anthropic",
    )
    oe.add_argument(
        "--model",
        help="model ID; defaults to Claude Opus 5.5 for Anthropic, gpt-6.1-sol for OpenAI",
    )
    oe.add_argument("--api-base", help="compatible endpoint; required for --backend compatible")
    oe.add_argument("--iterations", type=int, default=100)
    oe.add_argument("--islands", type=int, default=5)
    oe.add_argument("--workers", type=int, default=3)
    oe.add_argument("--migration-interval", type=int, default=10)
    oe.add_argument("--checkpoint-interval", type=int, default=10)
    oe.add_argument("--seed", type=int, default=0)
    oe.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="high")
    oe.add_argument("--max-tokens", type=int, default=128000)
    oe.add_argument("--model-timeout", type=int, default=3600)
    oe.add_argument("--out", type=Path)
    oe.add_argument("--prepare-only", action="store_true", help="write a plan without API requests")
    oe.add_argument(
        "--smoke-test", action="store_true", help="real engine with offline toy proposals"
    )
    continuing = oe.add_mutually_exclusive_group()
    continuing.add_argument("--resume", action="store_true")
    continuing.add_argument("--checkpoint", type=Path)
    _evaluation_options(oe)
    census_parser = commands.add_parser("divsteps", help="validate integer branch recovery")
    census_parser.add_argument("--samples", type=int, default=1000)
    census_parser.add_argument("--seed", type=int, default=0)
    census_parser.add_argument("--store-depth", type=int, default=5)
    census_parser.add_argument("--out", type=Path, default=Path("runs/divsteps.json"))
    oracle = commands.add_parser("oracle", help="query a task's public classical reference")
    oracle.add_argument("task", choices=(*TASKS, "toy-gf-inverse"))
    oracle.add_argument("function")
    oracle.add_argument("--args", default="[]", help="JSON positional arguments")
    return root


def _evaluation_options(target: argparse.ArgumentParser) -> None:
    target.add_argument("--timeout", type=float, default=3600, help="total seconds per candidate")
    target.add_argument("--jobs", type=int, default=1)
    target.add_argument("--kernel", choices=["auto", "python", "c"], default="auto")
    _sandbox_options(target)


def _sandbox_options(target: argparse.ArgumentParser) -> None:
    target.add_argument(
        "--execution",
        choices=["docker", "local"],
        default="docker",
        help="docker isolates candidate code; local is for trusted programs only",
    )
    target.add_argument("--docker-image", default=DEFAULT_IMAGE)
    target.add_argument("--sandbox-cpus", type=float, default=2)
    target.add_argument("--sandbox-memory-mb", type=int, default=4096)
    target.add_argument("--sandbox-pids", type=int, default=256)
    target.add_argument("--sandbox-tmp-mb", type=int, default=1024)
    target.add_argument("--sandbox-max-ops-mb", type=int, default=1024)


def _sandbox_config(args: argparse.Namespace) -> SandboxConfig:
    return SandboxConfig(
        mode=args.execution,
        image=args.docker_image,
        cpus=args.sandbox_cpus,
        memory_mb=args.sandbox_memory_mb,
        pids=args.sandbox_pids,
        tmp_mb=args.sandbox_tmp_mb,
        max_ops_mb=args.sandbox_max_ops_mb,
    )


def _tasks(names: list[str]) -> list[str]:
    result = []
    for name in names:
        if name == "all":
            result.extend(TASKS)
        elif name == "numerical":
            result.extend(NUMERICAL_TASKS)
        elif name in TASKS:
            result.append(name)
        else:
            raise ValueError(f"Unknown task: {name}")
    return list(dict.fromkeys(result))


def environment() -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "galois", "mpmath", "click")
        },
        "upstream_commit": UPSTREAM_COMMIT,
    }


def reproduce(args: argparse.Namespace) -> int:
    tasks = _tasks(args.tasks)
    variants = ["discovered", "baseline"] if args.variant == "both" else [args.variant]
    rows = []
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "environment.json", environment())
    for task in tasks:
        for variant in variants:
            print(f"Evaluating {task}/{variant} ...", flush=True)
            directory = args.out / task / variant
            result = evaluate(
                task,
                circuit_path(task, variant),
                directory,
                timeout=args.timeout,
                jobs=args.jobs,
                shots=args.shots,
                kernel=args.kernel,
                sandbox=_sandbox_config(args),
            )
            row = compare_published(result, variant)
            rows.append(row)
            write_json(directory / "comparison.json", row)
            status = "REPRODUCED" if row["reproduced"] else "DIAGNOSTIC" if result.valid else "FAIL"
            print(f"  {status}: {result.metrics}", flush=True)
            # A partial run remains reviewable even when a later task times out.
            write_json(args.out / "summary.json", {"results": rows})
    table = [
        "| Task | Circuit | Measured T | Measured Q | Hash match | Full reproduction |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in rows:
        measured = row["measured"]
        table.append(
            f"| {row['task']} | {row['variant']} | {measured.get('toffoli', '—')} "
            f"| {measured.get('qubits', '—')} | {row['matches']['h_ops']} | {row['reproduced']} |"
        )
    (args.out / "table.md").write_text("\n".join(table) + "\n")
    return 0 if all(r["valid"] and all(r["matches"].values()) for r in rows) else 1


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        code = _main(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


def _main(args: argparse.Namespace) -> int:
    if args.command == "openevolve":
        from qdiscover.openevolve_search import (
            DEFAULT_MODEL,
            OpenEvolveSettings,
            run_openevolve,
        )

        model = args.model or os.environ.get("QDISCOVER_MODEL")
        if model is None:
            model = {"anthropic": DEFAULT_MODEL, "openai": "gpt-6.1-sol"}.get(args.backend)
        if not model:
            raise ValueError("Specify --model or QDISCOVER_MODEL for this backend")
        options = {
            field.name: getattr(args, field.name)
            for field in fields(OpenEvolveSettings)
            if hasattr(args, field.name)
        }
        options.update(model=model, timeout=int(args.timeout), sandbox=_sandbox_config(args))
        settings = OpenEvolveSettings(**options)
        result = run_openevolve(
            settings,
            args.out or Path("runs") / args.task,
            prepare_only=args.prepare_only,
            resume=args.resume,
            checkpoint=args.checkpoint,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if args.prepare_only or result.get("best_valid") else 1
    if args.command == "upstream-setup":
        setup_upstream()
        print(f"Upstream ready: {UPSTREAM_COMMIT}")
        return 0
    if args.command == "kernel":
        print(build_kernel())
        return 0
    if args.command == "docker-build":
        print(build_image(args.context, args.image))
        return 0
    if args.command == "list":
        print(json.dumps([asdict(published_result(t, "discovered")) for t in TASKS], indent=2))
        return 0
    if args.command == "reproduce":
        return reproduce(args)
    if args.command == "evaluate":
        result = evaluate(
            args.task,
            args.source,
            args.out,
            timeout=args.timeout,
            jobs=args.jobs,
            kernel=args.kernel,
            sandbox=_sandbox_config(args),
        )
        print(json.dumps(asdict(result), indent=2))
        return 0 if result.valid else 1
    if args.command == "divsteps":
        result = census(args.samples, args.seed, args.store_depth)
        write_json(args.out, result)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "oracle":
        # Isolate reference imports like grader imports; no source is sent to the model.
        command = [sys.executable, "-m", "qdiscover.oracle", args.task, args.function, args.args]
        result = run_process(command, cwd=Path.cwd(), env=execution_env(args.task), timeout=120)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    raise ValueError(f"Unknown command: {args.command}")
