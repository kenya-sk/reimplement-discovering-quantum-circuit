from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qdiscover.api_cost import USAGE_DIRECTORY_ENV, cost_summary, record_usage
from qdiscover.openevolve_llm import AnthropicLLM
from qdiscover.openevolve_search import OpenEvolveSettings, run_openevolve
from qdiscover.sandbox import SandboxConfig

MODEL = "claude-opus-5-5"


def test_cost_includes_parallel_workers_cache_and_previous_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = tmp_path / "previous"
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(previous))
    record_usage(MODEL, {"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    session = tmp_path / "current"
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(session))
    usage = {
        "input_tokens": 1000,
        "output_tokens": 2000,
        "cache_read_input_tokens": 3000,
        "cache_creation_input_tokens": 9000,
        "cache_creation": {"ephemeral_5m_input_tokens": 4000, "ephemeral_1h_input_tokens": 5000},
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: record_usage(MODEL, usage), range(20)))
    # A child process inherits the recording destination, like an OpenEvolve worker.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from qdiscover.api_cost import record_usage; "
            f"record_usage('{MODEL}', {{'input_tokens': 1000000, 'output_tokens': 0}})",
        ],
        check=True,
    )
    result = cost_summary(session)
    assert result["current_run"]["requests"] == 21
    assert result["current_run"]["estimated_cost_usd"] == pytest.approx(6.092)
    assert result["cumulative"]["estimated_cost_usd"] == pytest.approx(30.092)
    assert result["current_run"]["tokens"]["cache_creation_1h_input_tokens"] == 100_000


@pytest.mark.parametrize("failure", ["truncated", "transport", "missing_usage"])
def test_usage_is_recorded_even_when_response_cannot_be_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(tmp_path / "session"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")

    def request(**kwargs: Any) -> dict[str, Any]:
        if failure == "transport":
            raise RuntimeError("connection lost")
        return {
            "content": [{"type": "text", "text": "partial"}],
            "stop_reason": "max_tokens" if failure == "truncated" else "end_turn",
            "usage": None
            if failure == "missing_usage"
            else {"input_tokens": 1_000_000, "output_tokens": 100_000},
        }

    monkeypatch.setattr("qdiscover.openevolve_llm.request_message", request)
    client = AnthropicLLM(SimpleNamespace(name=MODEL, max_tokens=100, timeout=10))
    if failure == "missing_usage":
        asyncio.run(client.generate_with_context("", []))
    else:
        with pytest.raises((ValueError, RuntimeError)):
            asyncio.run(client.generate_with_context("", []))
    result = cost_summary(tmp_path / "session")["current_run"]
    assert result["requests"] == 1
    assert result["estimated_cost_usd"] == (6 if failure == "truncated" else 0)
    assert result["requests_without_usage"] == (0 if failure == "truncated" else 1)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (MODEL, 6),
        ("claude-fable-5-2", 12),
        ("claude-sonnet-5-5", 3),
        ("claude-haiku-5-5", 0.75),
        ("gpt-6.1-sol", 5.5),
        ("gpt-6.1-terra", 2.75),
        ("gpt-6-luna", 0.275),
    ],
)
def test_run_reports_cost_on_failure_and_accumulates_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    model: str,
    expected: float,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.delenv(USAGE_DIRECTORY_ENV, raising=False)
    monkeypatch.setattr("qdiscover.openevolve_search.require_openevolve", lambda: None)

    def engine(*args: Any, **kwargs: Any) -> dict[str, Any]:
        record_usage(model, {"input_tokens": 1_000_000, "output_tokens": 100_000})
        raise RuntimeError("failed after API response")

    monkeypatch.setattr("qdiscover.openevolve_search._run_engine", engine)
    settings = OpenEvolveSettings(
        "toy-gf-inverse",
        model=model,
        backend="openai" if model.startswith("gpt-") else "anthropic",
        sandbox=SandboxConfig(mode="local"),
    )
    for _ in range(2):
        with pytest.raises(RuntimeError, match="failed after"):
            run_openevolve(settings, tmp_path)
    result = json.loads((tmp_path / "summary.json").read_text())
    assert result["status"] == "failed"
    assert result["api_cost"]["model"] == model
    assert result["api_cost"]["current_run"]["estimated_cost_usd"] == expected
    assert result["api_cost"]["cumulative"]["estimated_cost_usd"] == expected * 2
    if model == "claude-fable-5-2":
        assert result["api_cost"]["pricing_checked_on"] == "2026-11-10"
        assert result["api_cost"]["pricing_source"] == (
            "https://platform.claude.com/docs/en/about-claude/pricing"
        )
    assert json.loads((tmp_path / "api_cost.json").read_text()) == result["api_cost"]
    assert f"this run ${expected:.6f}; cumulative ${expected * 2:.6f}" in capsys.readouterr().err
    assert USAGE_DIRECTORY_ENV not in os.environ
    assert "test-placeholder" not in (tmp_path / "summary.json").read_text()


@pytest.mark.parametrize(
    ("model", "extra_input", "expected"),
    [
        ("claude-fable-5-2", 0, 3.024),
        ("claude-fable-5-2", 900_000, 10.224),
        ("claude-sonnet-5-5", 0, 0.757),
        ("claude-haiku-5-5", 0, 0.03795),
        ("claude-haiku-5-5", 1, 0.1897505),
    ],
)
def test_model_cache_rates_and_haiku_prompt_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    extra_input: int,
    expected: float,
) -> None:
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(tmp_path / "session"))
    record_usage(
        model,
        {
            "input_tokens": 10_000 + extra_input,
            "output_tokens": 50_000,
            "cache_read_input_tokens": 20_000,
            "cache_creation_input_tokens": 70_000,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 30_000,
                "ephemeral_1h_input_tokens": 40_000,
            },
        },
    )
    result = cost_summary(tmp_path / "session", model)["current_run"]
    assert result["requests_without_usage"] == 0
    assert result["estimated_cost_usd"] == pytest.approx(expected)


def test_completed_run_and_checkpoint_resume_report_separate_and_total_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, "previous-destination")
    monkeypatch.setattr("qdiscover.openevolve_search.require_openevolve", lambda: None)

    def engine(
        settings: Any, out: Path, continuing: bool, checkpoint: Any, context: Any
    ) -> dict[str, Any]:
        if not continuing:
            # Represents the initial ideation call, which is skipped on resume.
            record_usage(MODEL, {"input_tokens": 1_000_000, "output_tokens": 0})
        record_usage(MODEL, {"input_tokens": 0, "output_tokens": 1_000_000})
        return {"status": "completed"}

    monkeypatch.setattr("qdiscover.openevolve_search._run_engine", engine)
    settings = OpenEvolveSettings("toy-gf-inverse", sandbox=SandboxConfig(mode="local"))
    first = run_openevolve(settings, tmp_path)
    assert first["api_cost"]["current_run"]["estimated_cost_usd"] == 24
    checkpoint = tmp_path / "engine" / "checkpoints" / "checkpoint_1"
    checkpoint.mkdir(parents=True)
    (checkpoint / "metadata.json").write_text("{}")
    resumed = run_openevolve(settings, tmp_path, resume=True)
    assert resumed["status"] == "completed"
    assert resumed["api_cost"]["current_run"]["estimated_cost_usd"] == 20
    assert resumed["api_cost"]["cumulative"]["estimated_cost_usd"] == 44
    assert os.environ[USAGE_DIRECTORY_ENV] == "previous-destination"
