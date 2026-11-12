import sys
from pathlib import Path

from qdiscover.process import run_process


def test_process_timeout_and_json_input(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout=0.1
    )
    assert result.timed_out
    assert result.returncode != 0
    result = run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        cwd=tmp_path,
        timeout=5,
        input_text='{"hello": 1}',
    )
    assert not result.timed_out
    assert result.stdout.strip() == '{"hello": 1}'
