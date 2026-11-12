"""Offline validation of native OpenAI requests and API cost accounting."""

import asyncio
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from qdiscover.api_cost import OPENAI_RATES, USAGE_DIRECTORY_ENV, cost_summary, record_usage
from qdiscover.openevolve_llm import OpenAILLM, credential_variable, openai_client
from qdiscover.openevolve_search import OpenEvolveSettings, _llm_config


def stream(*events: dict[str, Any]) -> io.BytesIO:
    return io.BytesIO(
        "".join(f"event: {e['type']}\r\ndata: {json.dumps(e)}\r\n\r\n" for e in events).encode()
    )


@pytest.mark.parametrize("model", OPENAI_RATES)
@pytest.mark.parametrize(
    "status",
    ["completed", "incomplete", "failed", "empty", "transport", "disconnect", "error", "timeout"],
)
def test_openai_request_and_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: str, status: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(tmp_path / "session"))
    config = _llm_config(OpenEvolveSettings("toy-gf-inverse", backend="openai", model=model))
    assert config.models[0].init_client is openai_client
    assert credential_variable("openai") == "OPENAI_API_KEY"
    client = OpenAILLM(config.models[0])

    def urlopen(request: Any, timeout: float) -> Any:
        assert request.full_url == "https://api.openai.com/v1/responses"
        assert request.get_header("Authorization") == "Bearer test-placeholder"
        body = json.loads(request.data)
        assert body["model"] == model
        assert body["reasoning"] == {"effort": "high"}
        assert body["instructions"] == "system"
        assert body["input"] == [{"role": "user", "content": "prompt"}]
        assert body["max_output_tokens"] == 1234
        assert body["service_tier"] == "default"
        assert body["stream"] is True
        assert request.get_header("Accept") == "text/event-stream"
        assert "temperature" not in body
        if status == "transport":
            raise OSError("connection lost")
        events = [
            {"type": "response.created", "response": {"status": "in_progress", "usage": None}},
            {"type": "response.output_text.delta", "delta": "co"},
            {"type": "future_event"},
            {"type": "response.output_text.delta", "delta": "de"},
        ]
        if status == "timeout":

            class InterruptedStream:
                def __enter__(self) -> Iterator[bytes]:
                    return self.lines()

                def __exit__(self, *args: Any) -> None:
                    pass

                def lines(self) -> Iterator[bytes]:
                    yield from stream(*events)
                    raise TimeoutError("read timed out")

            return InterruptedStream()
        if status == "disconnect":
            return stream(*events)
        if status == "error":
            return stream(*events, {"type": "error", "code": "server_error", "message": "failed"})
        terminal_status = "completed" if status == "empty" else status
        return stream(
            *events,
            {
                "type": f"response.{terminal_status}",
                "response": {
                    "status": terminal_status,
                    "usage": {"input_tokens": 1000, "output_tokens": 2000},
                    "output": []
                    if status == "empty"
                    else [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "code"}],
                        }
                    ],
                },
            },
        )

    monkeypatch.setattr("qdiscover.openevolve_llm.urllib.request.urlopen", urlopen)
    call = client.generate_with_context(
        "system", [{"role": "user", "content": "prompt"}], max_tokens=1234
    )
    if status == "completed":
        assert asyncio.run(call) == "code"
        assert client.last_usage == {"input_tokens": 1000, "output_tokens": 2000}
    else:
        with pytest.raises((OSError, ValueError, RuntimeError)):
            asyncio.run(call)
    result = cost_summary(tmp_path / "session", model)
    assert result["current_run"]["requests"] == 1
    assert result["current_run"]["requests_without_usage"] == int(
        status in {"transport", "disconnect", "error", "timeout"}
    )
    assert result["current_run"]["estimated_cost_usd"] == pytest.approx(
        0
        if status in {"transport", "disconnect", "error", "timeout"}
        else float(OPENAI_RATES[model]["input_tokens"]) * 0.001
        + float(OPENAI_RATES[model]["output_tokens"]) * 0.002
    )
    assert "test-placeholder" not in json.dumps(result)


@pytest.mark.parametrize(
    "model,base", [("gpt-6.1-sol", 2), ("gpt-6.1-terra", 1), ("gpt-6-luna", 0.1)]
)
@pytest.mark.parametrize("input_tokens", [272_000, 272_001])
def test_openai_cache_and_long_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: str, base: float, input_tokens: int
) -> None:
    monkeypatch.setenv(USAGE_DIRECTORY_ENV, str(tmp_path / "session"))
    record_usage(
        model,
        {
            "input_tokens": input_tokens,
            "output_tokens": 10_000,
            "input_tokens_details": {
                "cached_tokens": 40_000,
                "cache_write_tokens": 70_000,
                "cache_write_tokens_details": {"ttl_30m_tokens": 30_000, "ttl_12h_tokens": 40_000},
            },
            "output_tokens_details": {"reasoning_tokens": 9000},
        },
    )
    result = cost_summary(tmp_path / "session", model)["current_run"]
    read_multiplier = 0.1 if model == "gpt-6-luna" else 0.05
    input_cost = base * (
        input_tokens - 110_000 + 40_000 * read_multiplier + 30_000 * 1.25 + 40_000 * 2.5
    )
    output_cost = base * 5 * 10_000
    if input_tokens > 272_000:
        input_cost *= 2
        output_cost *= 1.5
    assert result["estimated_cost_usd"] == pytest.approx((input_cost + output_cost) / 1_000_000)
    assert result["tokens"]["input_tokens"] == input_tokens - 110_000
    assert result["tokens"]["output_tokens"] == 10_000
