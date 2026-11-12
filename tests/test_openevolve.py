from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qdiscover.openevolve_evaluator import admit_valid
from qdiscover.openevolve_llm import AnthropicLLM, compatible_client
from qdiscover.openevolve_search import OpenEvolveSettings, build_config, run_openevolve
from qdiscover.process import run_process
from qdiscover.sandbox import SandboxConfig
from qdiscover.toy_task.circuit import inverse_circuit

HAS_OPENEVOLVE = importlib.util.find_spec("openevolve") is not None
requires_engine = pytest.mark.skipif(not HAS_OPENEVOLVE, reason="Install --extra openevolve")
LOCAL = SandboxConfig(mode="local")


def test_invalid_candidates_are_not_admitted() -> None:
    assert not admit_valid(None, SimpleNamespace(metrics={"valid": 0.0}), 0)
    assert admit_valid(None, SimpleNamespace(metrics={"valid": 1.0}), 0)
    assert admit_valid(
        None, SimpleNamespace(parent_id=None, generation=0, metrics={"valid": 0.0}), 0
    )


@requires_engine
def test_prepare_does_not_call_the_model_or_store_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Preparation must not call the API")

    monkeypatch.setattr("urllib.request.urlopen", unexpected)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-must-not-appear")
    settings = OpenEvolveSettings("toy-gf-inverse")
    assert settings.model == "claude-opus-5-5"
    assert (settings.effort, settings.max_tokens, settings.model_timeout) == ("high", 32768, 1200)
    plan = run_openevolve(settings, tmp_path, prepare_only=True)
    assert plan["engine"] == "openevolve==0.4.1"
    assert "placeholder-must-not-appear" not in (tmp_path / "run_settings.json").read_text()
    config = build_config(settings, tmp_path, [{"name": "a", "description": ""}] * 3)
    assert config.database.feature_dimensions == ["toffoli", "qubits"]
    assert config.evaluator.evaluator_args["task"] == "toy-gf-inverse"
    assert config.llm.api_key is None and all(m.api_key is None for m in config.llm.models)
    assert all(m.name == "claude-opus-5-5" for m in config.llm.models)
    assert all(m.reasoning_effort == "high" for m in config.llm.models)
    assert all(m.max_tokens == 32768 and m.timeout == 1200 for m in config.llm.models)


@requires_engine
def test_missing_key_fails_before_model_or_file_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        run_openevolve(OpenEvolveSettings("toy-gf-inverse"), tmp_path / "new")
    assert not (tmp_path / "new").exists()


@requires_engine
def test_failed_ideation_is_recorded_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("model unavailable")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-placeholder")
    monkeypatch.setattr("qdiscover.openevolve_search.ideate", fail)
    settings = OpenEvolveSettings("toy-gf-inverse", sandbox=LOCAL)
    with pytest.raises(RuntimeError, match="model unavailable"):
        run_openevolve(settings, tmp_path)
    saved = json.loads((tmp_path / "run_settings.json").read_text())
    assert saved["status"] == "failed"
    # Before a checkpoint exists the same directory can be prepared/retried.
    assert run_openevolve(settings, tmp_path, prepare_only=True)["status"] == "prepared"


@pytest.mark.parametrize("effort", ["high", "low"])
def test_anthropic_model_preserves_native_text_and_usage(
    monkeypatch: pytest.MonkeyPatch,
    effort: str,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> io.BytesIO:
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "```python\npass\n```"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]
        return io.BytesIO("".join(f"data: {json.dumps(e)}\n\n" for e in events).encode())

    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-test-placeholder")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AnthropicLLM(
        SimpleNamespace(name="test", max_tokens=32768, timeout=1200, reasoning_effort=effort)
    )
    text = asyncio.run(client.generate_with_context("system", [{"role": "user", "content": "x"}]))
    assert text == "```python\npass\n```"
    assert "temperature" not in captured["body"]
    assert captured["body"]["stream"] is True
    assert captured["body"]["output_config"] == {"effort": effort}
    assert captured["body"]["max_tokens"] == 32768
    assert captured["timeout"] == 1200
    assert client.last_usage == {"input_tokens": 10, "output_tokens": 5}


@requires_engine
@pytest.mark.parametrize(
    ("backend", "variable", "endpoint"),
    [
        ("openrouter", "OPENROUTER_API_KEY", None),
        ("openrouter", "OPENROUTER_API_KEY", "http://localhost:8000/v1"),
        ("gemini", "GEMINI_API_KEY", None),
        ("compatible", "OPENAI_API_KEY", "http://localhost:8000/v1"),
    ],
)
def test_compatible_client_uses_the_selected_key_without_mutating_saved_config(
    backend: str,
    variable: str,
    endpoint: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = OpenEvolveSettings("toy-gf-inverse", backend=backend, api_base=endpoint)
    config = build_config(settings, tmp_path, [{"name": "a", "description": ""}] * 3)
    monkeypatch.setenv(variable, "local-placeholder")
    monkeypatch.setattr("openevolve.llm.openai.OpenAILLM", lambda cfg: asdict(cfg))
    client = compatible_client(config.llm.models[0])
    assert client["api_key"] == "local-placeholder"
    assert config.llm.models[0].api_key is None


@requires_engine
@pytest.mark.integration
def test_adapter_scores_only_valid_full_evaluations(tmp_path: Path) -> None:
    from qdiscover.openevolve_evaluator import evaluate

    source = tmp_path / "circuit.py"
    source.write_text(inverse_circuit(anf=True))
    good = evaluate(
        str(source), task="toy-gf-inverse", out_dir=str(tmp_path / "results"), sandbox=asdict(LOCAL)
    )
    assert good.metrics["valid"] == 1
    assert good.metrics["combined_score"] == pytest.approx(1 / 19)
    source.write_text(inverse_circuit(anf=True).replace("b.emit()", "b.z(x[0])\nb.emit()"))
    bad = evaluate(
        str(source), task="toy-gf-inverse", out_dir=str(tmp_path / "results"), sandbox=asdict(LOCAL)
    )
    assert bad.metrics["valid"] == 0 and bad.metrics["combined_score"] == 0
    assert "report" in bad.artifacts and "INVALID" in bad.artifacts["verdict"]


@requires_engine
@pytest.mark.integration
def test_real_engine_smoke_and_checkpoint_resume(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "qdiscover",
        "openevolve",
        "toy-gf-inverse",
        "--smoke-test",
        "--execution",
        "local",
        "--iterations",
        "2",
        "--islands",
        "2",
        "--checkpoint-interval",
        "1",
        "--out",
        str(tmp_path),
    ]
    first = run_process(command, cwd=Path.cwd(), timeout=120)
    assert first.returncode == 0, first.stdout + first.stderr
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["best_valid"] and summary["best_metrics"]["tq_cost"] == 18
    assert list((tmp_path / "engine" / "checkpoints").glob("checkpoint_*"))
    second = run_process(command + ["--resume"], cwd=Path.cwd(), timeout=120)
    assert second.returncode == 0, second.stdout + second.stderr
    with pytest.raises(ValueError, match="Run exists"):
        run_openevolve(OpenEvolveSettings("toy-gf-inverse", sandbox=LOCAL), tmp_path)


@requires_engine
def test_run_loads_dotenv_before_engine_without_saving_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text('ANTHROPIC_API_KEY="dotenv-test-placeholder"\n')

    def engine(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert os.environ["ANTHROPIC_API_KEY"] == "dotenv-test-placeholder"
        return {"best_valid": True}

    monkeypatch.setattr("qdiscover.openevolve_search._run_engine", engine)
    out = tmp_path / "run"
    result = run_openevolve(OpenEvolveSettings("toy-gf-inverse", sandbox=LOCAL), out)
    assert result["best_valid"]
    for name in ("run_settings.json", "summary.json"):
        assert "dotenv-test-placeholder" not in (out / name).read_text()


@pytest.mark.parametrize(
    "options, expected",
    [
        ([], ("high", 128000, 3600)),
        (
            ["--effort", "medium", "--max-tokens", "4096", "--model-timeout", "60"],
            ("medium", 4096, 60),
        ),
    ],
)
def test_cli_generation_settings(options: list[str], expected: tuple[str, int, int]) -> None:
    from qdiscover.cli import parser

    args = parser().parse_args(["openevolve", "coulomb-potential", *options])
    assert (args.effort, args.max_tokens, args.model_timeout) == expected
