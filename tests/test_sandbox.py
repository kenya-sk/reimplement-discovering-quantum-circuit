from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from qdiscover.evaluate import evaluate, execution_env
from qdiscover.process import ProcessResult, run_streamed_process
from qdiscover.sandbox import SandboxConfig, container_command, ensure_available


def test_evaluation_environment_does_not_inherit_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "PRIVATE_SENTINEL"]
    for key in private:
        monkeypatch.setenv(key, "local-placeholder")
    env = execution_env("toy-gf-inverse")
    assert not set(private) & env.keys()
    assert "QDISCOVER_TASK_DIR" in env and "PYTHONPATH" in env


def test_container_policy_has_only_readonly_file_mounts() -> None:
    command = container_command(
        SandboxConfig(),
        "sha256:test",
        "test",
        "toy-gf-inverse",
        "c",
        ["-m", "qdiscover.sandbox_worker", "/input/circuit.py"],
        [(Path("/tmp/circuit.py"), "/input/circuit.py")],
    )
    for flag in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--user=65532:65532",
        "--security-opt=no-new-privileges",
        "--memory=4096m",
        "--pids-limit=256",
    ):
        assert flag in command
    mounts = [command[i + 1] for i, arg in enumerate(command) if arg == "--mount"]
    assert mounts and all(m.endswith(",readonly") for m in mounts)
    assert not any("docker.sock" in arg or "API_KEY" in arg for arg in command)


def test_missing_docker_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "qdiscover.sandbox.run_process", lambda *a, **kw: ProcessResult(1, "", "Docker unavailable")
    )
    source = tmp_path / "source.py"
    marker = tmp_path / "must-not-execute"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    with pytest.raises(RuntimeError, match="Sandbox image unavailable"):
        evaluate("toy-gf-inverse", source, tmp_path / "result")
    assert not marker.exists()


def test_stale_image_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "qdiscover.sandbox.run_process",
        lambda *a, **kw: ProcessResult(0, json.dumps({"id": "old", "labels": {}}), ""),
    )
    with pytest.raises(RuntimeError, match="stale"):
        ensure_available(SandboxConfig())


def test_streamed_output_limit_and_deadline(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = run_streamed_process(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1000000)"],
        stdout_path=output,
        timeout=10,
        max_stdout_bytes=1024,
    )
    assert result.output_limited and output.stat().st_size <= 1024
    result = run_streamed_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout_path=output,
        timeout=0.1,
        max_stdout_bytes=1024,
    )
    assert result.timed_out
