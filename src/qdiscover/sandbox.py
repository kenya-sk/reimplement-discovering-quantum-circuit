"""Disposable Docker stages with no credentials, network, or host write mounts."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from qdiscover.catalog import UPSTREAM_COMMIT, UPSTREAM_ROOT, task_dir
from qdiscover.process import ProcessResult, run_process, run_streamed_process

DEFAULT_IMAGE = "qdiscover-evaluator:0.1.0"
CONTAINER_ROOT = Path("/opt/qdiscover/src/qdiscover")
CONTAINER_UPSTREAM = CONTAINER_ROOT / "_vendor" / "uncompute"
SOURCE_LABEL = "io.qdiscover.source-sha256"


@dataclass(frozen=True)
class SandboxConfig:
    mode: str = "docker"
    image: str = DEFAULT_IMAGE
    cpus: float = 2
    memory_mb: int = 4096
    pids: int = 256
    tmp_mb: int = 1024
    max_ops_mb: int = 1024

    def __post_init__(self) -> None:
        if self.mode not in {"docker", "local"}:
            raise ValueError("Execution mode must be docker or local")
        if not self.image or self.image.startswith("-") or any(c.isspace() for c in self.image):
            raise ValueError("Invalid Docker image reference")
        if not math.isfinite(self.cpus) or self.cpus <= 0:
            raise ValueError("Sandbox CPUs must be positive and finite")
        if min(self.memory_mb, self.pids, self.tmp_mb, self.max_ops_mb) < 1:
            raise ValueError("Sandbox resource limits must be positive")


def source_fingerprint(root: Path | None = None) -> str:
    root = root or Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or ".cache" in path.parts
            or ".aws" in path.parts
            or ".ssh" in path.parts
            or path.name == ".env"
            or path.name.startswith(".env.")
            or path.suffix in {".pyc", ".so", ".dylib"}
        ):
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_image(context: Path | None = None, image: str = DEFAULT_IMAGE) -> str:
    context = (context or Path(__file__).resolve().parents[2]).resolve()
    SandboxConfig(image=image)
    if not (context / "Dockerfile").is_file():
        raise ValueError("Run docker-build from the source checkout or specify --context")
    result = run_process(
        [
            "docker",
            "build",
            "--tag",
            image,
            "--label",
            f"{SOURCE_LABEL}={source_fingerprint(context / 'src' / 'qdiscover')}",
            "--label",
            f"io.qdiscover.upstream={UPSTREAM_COMMIT}",
            str(context),
        ],
        cwd=context,
        timeout=1800,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-16000:])
    return image


def ensure_available(config: SandboxConfig) -> dict[str, Any]:
    if config.mode == "local":
        return asdict(config)
    try:
        result = run_process(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                '{"id":{{json .Id}},"labels":{{json .Config.Labels}}}',
                config.image,
            ],
            cwd=Path.cwd(),
            timeout=20,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Docker is required; install and start Docker, then run qdiscover docker-build"
        ) from None
    if result.returncode:
        raise RuntimeError(
            "Sandbox image unavailable. Start Docker and run qdiscover docker-build. "
            + result.stderr[-2000:]
        )
    image = json.loads(result.stdout)
    if (image.get("labels") or {}).get(SOURCE_LABEL) != source_fingerprint():
        raise RuntimeError("Sandbox image is stale; rebuild it with qdiscover docker-build")
    return {**asdict(config), "image_id": image["id"]}


def container_task_dir(task: str) -> Path:
    task_dir(task)  # Validate before constructing container paths.
    return (
        CONTAINER_ROOT / "toy_task"
        if task == "toy-gf-inverse"
        else CONTAINER_UPSTREAM / "tasks" / task
    )


def container_command(
    config: SandboxConfig,
    image_id: str,
    name: str,
    task: str,
    kernel: str,
    arguments: list[str],
    mounts: list[tuple[Path, str]],
    *,
    lifetime: float = 3600,
) -> list[str]:
    command = [
        "docker",
        "create",
        "--attach=stdout",
        "--attach=stderr",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--user=65532:65532",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--entrypoint=/usr/bin/timeout",
        "--log-driver=none",
        f"--cpus={config.cpus}",
        f"--memory={config.memory_mb}m",
        f"--memory-swap={config.memory_mb}m",
        f"--pids-limit={config.pids}",
        "--shm-size=64m",
        "--ulimit=core=0:0",
        "--ulimit=nofile=4096:4096",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={config.tmp_mb}m,mode=1777",
        "--workdir",
        str(CONTAINER_UPSTREAM),
        "--env",
        f"QDISCOVER_TASK_DIR={container_task_dir(task)}",
    ]
    # Docker may otherwise inject proxy URLs (including proxy credentials)
    # from the controller's Docker client configuration into new containers.
    for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY"):
        command += ["--env", f"{proxy}=", "--env", f"{proxy.lower()}="]
    if kernel != "auto":
        command += ["--env", f"UNCOMPUTE_KERNEL={int(kernel == 'c')}"]
    for source, target in mounts:
        command += ["--mount", f"type=bind,src={source},dst={target},readonly"]
    return command + [
        image_id,
        "--kill-after=2s",
        f"{math.ceil(lifetime)}s",
        "/opt/qdiscover/.venv/bin/python",
        *arguments,
    ]


def _run_container(
    config: SandboxConfig,
    image_id: str,
    task: str,
    kernel: str,
    arguments: list[str],
    mounts: list[tuple[Path, str]],
    output: Path,
    timeout: float,
    max_output_bytes: int,
) -> ProcessResult:
    name = f"qdiscover-{uuid.uuid4().hex}"
    command = container_command(
        config, image_id, name, task, kernel, arguments, mounts, lifetime=timeout
    )
    started = time.monotonic()
    try:
        created = run_process(command, cwd=Path.cwd(), timeout=min(timeout, 20))
        if created.returncode:
            return created
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            return ProcessResult(-1, "", "Container creation exceeded the deadline", timed_out=True)
        result = run_streamed_process(
            ["docker", "start", "--attach", name],
            stdout_path=output,
            timeout=remaining,
            max_stdout_bytes=max_output_bytes,
        )
        return replace(result, timed_out=result.timed_out or result.returncode == 124)
    finally:
        # Killing the Docker client alone does not stop its container.
        cleanup = run_process(["docker", "rm", "--force", name], cwd=Path.cwd(), timeout=15)
        if cleanup.returncode and "No such container" not in cleanup.stderr:
            raise RuntimeError(f"Could not remove sandbox {name}: {cleanup.stderr[-2000:]}")


def build_circuit(
    config: SandboxConfig,
    image_id: str,
    task: str,
    source: Path,
    ops: Path,
    *,
    timeout: float,
    kernel: str,
) -> ProcessResult:
    with tempfile.TemporaryDirectory(prefix="qdiscover-source-") as directory:
        mounts = []
        if source.is_relative_to(UPSTREAM_ROOT.resolve()):
            candidate = str(CONTAINER_UPSTREAM / source.relative_to(UPSTREAM_ROOT.resolve()))
        else:
            staged = Path(directory) / "circuit.py"
            staged.write_bytes(source.read_bytes())
            staged.chmod(0o444)
            candidate = "/input/circuit.py"
            mounts = [(staged, candidate)]
        return _run_container(
            config,
            image_id,
            task,
            kernel,
            ["-m", "qdiscover.sandbox_worker", candidate],
            mounts,
            ops,
            timeout,
            config.max_ops_mb << 20,
        )


def judge_circuit(
    config: SandboxConfig,
    image_id: str,
    task: str,
    ops: Path,
    out: Path,
    *,
    timeout: float,
    kernel: str,
    jobs: int,
    shots: int | None,
) -> ProcessResult:
    arguments = [
        "-m",
        "qdiscover.worker",
        "--task-dir",
        str(container_task_dir(task)),
        "--ops",
        "/input/circuit.ops",
        "--out",
        "/tmp/report",
        "--jobs",
        str(jobs),
        "--json-only",
    ]
    if shots is not None:
        arguments += ["--shots", str(shots)]
    report_path = out / "container-report.json"
    result = _run_container(
        config,
        image_id,
        task,
        kernel,
        arguments,
        [(ops, "/input/circuit.ops")],
        report_path,
        timeout,
        1 << 20,
    )
    stdout = report_path.read_text(errors="replace") if report_path.exists() else ""
    return replace(result, stdout=stdout)
