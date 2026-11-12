from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from qdiscover.catalog import NUMERICAL_TASKS, circuit_path
from qdiscover.evaluate import compare_published, evaluate
from qdiscover.process import run_process
from qdiscover.sandbox import SandboxConfig, ensure_available
from qdiscover.toy_task.circuit import inverse_circuit

pytestmark = [pytest.mark.integration, pytest.mark.docker]


@pytest.fixture(scope="module", autouse=True)
def docker_image() -> None:
    if shutil.which("docker") is None:
        if os.environ.get("QDISCOVER_REQUIRE_DOCKER"):
            pytest.fail("Docker is required for this test run")
        pytest.skip("Docker is not installed")
    # An available daemon with a missing/stale image is an error, not a skipped check.
    result = run_process(["docker", "info", "--format", "{{.OSType}}"], cwd=Path.cwd(), timeout=20)
    if result.returncode:
        if os.environ.get("QDISCOVER_REQUIRE_DOCKER"):
            pytest.fail("Docker daemon is required for this test run")
        pytest.skip("Docker daemon is not accessible")
    ensure_available(SandboxConfig())


@pytest.mark.parametrize("task", NUMERICAL_TASKS)
@pytest.mark.parametrize("variant", ["discovered", "baseline"])
def test_paper_streams_are_identical_inside_docker(task: str, variant: str, tmp_path: Path) -> None:
    result = evaluate(task, circuit_path(task, variant), tmp_path, kernel="c", jobs=2, timeout=180)
    assert compare_published(result, variant)["reproduced"], result
    assert result.sandbox["mode"] == "docker" and result.sandbox["image_id"].startswith("sha256:")


def test_generated_code_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "PRIVATE_SENTINEL"):
        monkeypatch.setenv(name, "local-placeholder-must-not-leak")
    sentinel = tmp_path / "host-only-secret"
    sentinel.write_text("host-only-test-data")
    probe = textwrap.dedent(f"""
        import errno, os, socket
        from pathlib import Path
        import qdiscover
        assert os.getuid() == 65532
        secrets = {{'ANTHROPIC_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'PRIVATE_SENTINEL'}}
        assert not secrets & os.environ.keys()
        assert not os.environ.get('HTTP_PROXY') and not os.environ.get('http_proxy')
        assert not Path('/var/run/docker.sock').exists()
        assert not Path({str(sentinel)!r}).exists()
        for target in (Path(__file__), Path(qdiscover.__file__)):
            try:
                target.write_text('must not be written')
            except OSError as exc:
                assert exc.errno in (errno.EROFS, errno.EACCES)
            else:
                raise AssertionError('source is writable')
        status = Path('/proc/self/status').read_text()
        assert 'NoNewPrivs:\\t1' in status
        assert 'CapEff:\\t0000000000000000' in status
        assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(4096 * 1024**2)
        assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '256'
        sock = socket.socket()
        sock.settimeout(1)
        try:
            sock.connect(('1.1.1.1', 443))
        except OSError:
            pass
        else:
            raise AssertionError('network is available')
        finally:
            sock.close()
        Path('/tmp/allowed').write_text('temporary scratch only')
        print('SANDBOX_PROBE_OK')
    """)
    source = tmp_path / "probe.py"
    source.write_text(probe + inverse_circuit(anf=True))
    out = tmp_path / "result"
    result = evaluate("toy-gf-inverse", source, out, timeout=60)
    assert result.valid, result
    assert "SANDBOX_PROBE_OK" in (out / "build.stderr.log").read_text()
    assert sentinel.read_text() == "host-only-test-data"


def test_builder_cannot_modify_the_independent_verdict(tmp_path: Path) -> None:
    source = tmp_path / "forged.py"
    source.write_text(
        "import uncompute.evalcore.task\n"
        "uncompute.evalcore.task.Task.check_shot = lambda *args: True\n"
        "from pathlib import Path\n"
        "Path('/tmp/report').mkdir()\n"
        "Path('/tmp/report/report.json').write_text('{\"verdict\":\"OK\"}')\n"
        + inverse_circuit(anf=True).replace("b.emit()", "b.x(y[0])\nb.emit()")
    )
    result = evaluate("toy-gf-inverse", source, tmp_path / "result", timeout=60)
    assert not result.valid and result.report["verdict"] == "FAIL"


def test_docker_python_and_c_kernels_agree(tmp_path: Path) -> None:
    results = [
        evaluate(
            "coulomb-potential",
            circuit_path("coulomb-potential"),
            tmp_path / kernel,
            kernel=kernel,
            timeout=120,
        )
        for kernel in ("python", "c")
    ]
    assert all(r.valid for r in results)
    assert results[0].metrics == results[1].metrics
    assert results[0].report["h_ops"] == results[1].report["h_ops"]


def test_timeout_removes_the_actual_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import qdiscover.sandbox as sandbox

    names: list[str] = []
    original = sandbox.container_command

    def record(*args: Any, **kwargs: Any) -> list[str]:
        command = original(*args, **kwargs)
        names.append(command[command.index("--name") + 1])
        return command

    monkeypatch.setattr(sandbox, "container_command", record)
    source = tmp_path / "loop.py"
    source.write_text("while True: pass\n")
    result = evaluate("toy-gf-inverse", source, tmp_path / "result", timeout=2)
    assert not result.valid and result.error == "build/timeout"
    assert names
    for name in names:
        check = run_process(["docker", "container", "inspect", name], cwd=tmp_path, timeout=20)
        assert check.returncode != 0


@pytest.mark.skipif(
    importlib.util.find_spec("openevolve") is None, reason="Install --extra openevolve"
)
def test_openevolve_uses_docker_without_a_model_api(tmp_path: Path) -> None:
    result = run_process(
        [
            sys.executable,
            "-m",
            "qdiscover",
            "openevolve",
            "toy-gf-inverse",
            "--smoke-test",
            "--iterations",
            "1",
            "--islands",
            "1",
            "--out",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["best_valid"] and summary["final_evaluation"]["sandbox"]["mode"] == "docker"
