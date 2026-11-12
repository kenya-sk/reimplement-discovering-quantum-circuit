from __future__ import annotations

import io
import json
import urllib.error
from collections.abc import Iterator
from typing import Any

import pytest

from qdiscover.llm import _read_stream, message_text, request_message


def test_messages_request_version_and_http_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: Any, timeout: float) -> Any:
        assert request.get_header("Anthropic-version") == "2026-10-21"
        body = json.loads(request.data)
        assert body["model"] == "claude-opus-5-5"
        assert body["stream"] is True
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {},  # type: ignore[arg-type]
            io.BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "message": "unsupported API version (test-placeholder)",
                        }
                    }
                ).encode()
            ),
        )

    monkeypatch.setattr("qdiscover.llm.urllib.request.urlopen", urlopen)
    with pytest.raises(RuntimeError, match="Claude API HTTP 400: invalid_request_error") as caught:
        request_message(
            model="claude-opus-5-5",
            api_key="test-placeholder",
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=32,
            timeout=5,
        )
    assert "unsupported API version" in str(caught.value)
    assert "test-placeholder" not in str(caught.value)


def stream(*events: dict[str, Any]) -> io.BytesIO:
    return io.BytesIO(
        "".join(f"event: {e['type']}\r\ndata: {json.dumps(e)}\r\n\r\n" for e in events).encode()
    )


def test_stream_collects_text_thinking_and_cumulative_usage() -> None:
    response = _read_stream(
        stream(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "content": [],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 30,
                        "cache_creation": {"ephemeral_5m_input_tokens": 30},
                    },
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "hidden reasoning"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            },
            {"type": "content_block_stop", "index": 0},
            {"type": "ping"},
            {"type": "future_event"},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "circuit\n"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "```python\npass\n```"},
            },
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 4}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 7, "output_tokens_details": {"thinking_tokens": 3}},
            },
            {"type": "message_stop"},
        )
    )
    assert message_text(response) == "circuit\n```python\npass\n```"
    assert response["id"] == "msg_test"
    assert response["content"][0]["signature"] == "sig"
    assert response["usage"] == {
        "input_tokens": 10,
        "output_tokens": 7,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 30,
        "cache_creation": {"ephemeral_5m_input_tokens": 30},
        "output_tokens_details": {"thinking_tokens": 3},
    }


def test_sse_comments_and_multiline_data() -> None:
    response = _read_stream(
        io.BytesIO(
            b": keep alive\r\n\r\nevent: message_start\r\n"
            b'data: {"type":"message_start",\r\ndata: "message":{"usage":{}}}\r\n\r\n'
            b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
            b'data: {"type":"message_stop"}\n\n'
        )
    )
    assert response["stop_reason"] == "end_turn"


def test_stream_surfaces_api_errors_after_http_success() -> None:
    with pytest.raises(RuntimeError, match="overloaded_error.*Overloaded"):
        _read_stream(
            stream(
                {
                    "type": "error",
                    "error": {
                        "type": "overloaded_error",
                        "message": "Overloaded",
                    },
                }
            )
        )


@pytest.mark.parametrize("tail", [b"", b'data: {"type":"message_stop"}'])
def test_disconnect_never_returns_a_partial_message(tail: bytes) -> None:
    data = stream({"type": "message_start", "message": {"usage": {"input_tokens": 10}}})
    with pytest.raises(RuntimeError, match="disconnected"):
        _read_stream(io.BytesIO(data.getvalue() + tail))


def test_socket_timeout_is_propagated() -> None:
    def interrupted() -> Iterator[bytes]:
        yield from stream({"type": "message_start", "message": {"usage": {}}})
        raise TimeoutError("The read operation timed out")

    with pytest.raises(TimeoutError, match="read operation timed out"):
        _read_stream(interrupted())


def test_streamed_token_limit_remains_an_error_with_usage_preserved() -> None:
    response = _read_stream(
        stream(
            {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "max_tokens"},
                "usage": {"output_tokens": 100},
            },
            {"type": "message_stop"},
        )
    )
    assert response["usage"]["output_tokens"] == 100
    with pytest.raises(ValueError, match="truncated"):
        message_text(response)


def test_message_stop_with_an_unfinished_block_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="incomplete message"):
        _read_stream(
            stream(
                {"type": "message_start", "message": {}},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": "partial"},
                },
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            )
        )
