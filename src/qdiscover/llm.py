"""Shared Claude transport and model-response parsing."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.partition("\n")[2].removesuffix("```")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def message_text(response: dict[str, Any]) -> str:
    if response.get("stop_reason") == "max_tokens":
        raise ValueError("Model output was truncated; increase --max-tokens")
    text = "".join(b["text"] for b in response.get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise ValueError("Claude returned no text")
    return text


def _stream_events(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Decode SSE frames, including comments, CRLF and multiline data fields."""
    data: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield json.loads("\n".join(data))
                data.clear()
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    # An unterminated final frame cannot establish successful completion.


def _read_stream(lines: Iterable[bytes]) -> dict[str, Any]:
    message: dict[str, Any] | None = None
    blocks: dict[int, dict[str, Any]] = {}
    open_blocks: set[int] = set()
    received_delta = False
    for event in _stream_events(lines):
        kind = event.get("type")
        if kind == "error":
            error = event.get("error", {})
            raise RuntimeError(
                f"Claude streaming error ({error.get('type', 'unknown')}): "
                f"{error.get('message', 'No details')}"
            )
        if kind == "message_start":
            message = dict(event["message"])
            message["content"] = []
        elif kind == "content_block_start":
            index = event["index"]
            blocks[index] = event["content_block"]
            open_blocks.add(index)
        elif kind == "content_block_delta":
            block = blocks[event["index"]]
            delta = event["delta"]
            field = {
                "text_delta": "text",
                "thinking_delta": "thinking",
                "signature_delta": "signature",
            }.get(delta.get("type"))
            if field:
                block[field] = block.get(field, "") + delta[field]
        elif kind == "content_block_stop":
            open_blocks.discard(event["index"])
        elif kind == "message_delta" and message is not None:
            message.update(event.get("delta", {}))
            # Counts are cumulative, not increments. Preserve input/cache usage
            # from message_start when message_delta only supplies output usage.
            message.setdefault("usage", {}).update(event.get("usage", {}))
            received_delta = True
        elif kind == "message_stop":
            if message is None or not received_delta or open_blocks:
                raise RuntimeError("Claude stream ended with an incomplete message")
            message["content"] = [blocks[index] for index in sorted(blocks)]
            return message
        # Ignore ping and future event types as required by the streaming API.
    raise RuntimeError("Claude stream disconnected before message_stop; response is incomplete")


def request_message(
    *,
    model: str,
    api_key: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    timeout: float,
    effort: str | None = None,
) -> dict[str, Any]:
    # Sampling parameters are omitted to support models that disallow them.
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    if effort is not None:
        body["output_config"] = {"effort": effort}
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2026-10-21",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _read_stream(response)
    except urllib.error.HTTPError as exc:
        with exc:
            detail = exc.read(65536).decode("utf-8", errors="replace")
        try:
            error = json.loads(detail)["error"]
            detail = f"{error['type']}: {error['message']}"
        except (ValueError, KeyError, TypeError):
            detail = detail.strip() or exc.reason
        detail = str(detail).replace(api_key, "[REDACTED]") if api_key else str(detail)
        raise RuntimeError(f"Claude API HTTP {exc.code}: {detail[:2000]}") from None
