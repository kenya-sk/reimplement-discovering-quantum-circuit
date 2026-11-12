"""Picklable model factories for OpenEvolve's documented init_client hook."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import urllib.request
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from qdiscover.api_cost import record_usage
from qdiscover.llm import _stream_events, message_text, request_message


def _read_openai_stream(lines: Iterable[bytes]) -> dict[str, Any]:
    """Consume SSE incrementally; only a terminal response establishes completion."""
    for event in _stream_events(lines):
        kind = event.get("type")
        if kind in {"response.completed", "response.incomplete", "response.failed"}:
            response = event["response"]
            if response.get("status") != kind.removeprefix("response."):
                raise ValueError("OpenAI stream terminal event has inconsistent status")
            # Terminal responses include the full output and final token usage.
            return response
        if kind == "error":
            raise RuntimeError(
                f"OpenAI streaming error ({event.get('code', 'unknown')}): "
                f"{event.get('message', 'No details')}"
            )
        # Deltas, progress notifications and future event types are consumed as
        # they arrive. The final response is authoritative for output and usage.
    raise RuntimeError(
        "OpenAI stream disconnected before terminal response; response is incomplete"
    )


class AnthropicLLM:
    """Native Messages API; credentials stay in the environment, outside saved config."""

    def __init__(self, config: Any):
        self.config = config
        self.last_usage: dict[str, Any] | None = None

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return await self.generate_with_context(
            self.config.system_message or "",
            [{"role": "user", "content": prompt}],
            **kwargs,
        )

    async def generate_with_context(
        self, system_message: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> str:
        return await asyncio.to_thread(self._request, system_message, messages, kwargs)

    def _request(self, system: str, messages: list[dict[str, str]], options: dict[str, Any]) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("Set ANTHROPIC_API_KEY before starting OpenEvolve")
        try:
            value = request_message(
                model=self.config.name,
                api_key=key,
                system=system,
                messages=messages,
                max_tokens=options.get("max_tokens", self.config.max_tokens),
                timeout=self.config.timeout,
                effort=getattr(self.config, "reasoning_effort", None),
            )
        except Exception:
            record_usage(self.config.name, None)
            raise
        self.last_usage = value.get("usage")
        record_usage(self.config.name, self.last_usage)
        return message_text(value)


def anthropic_client(config: Any) -> AnthropicLLM:
    return AnthropicLLM(config)


class OpenAILLM:
    """Native Responses API with durable usage recording before output validation."""

    def __init__(self, config: Any):
        self.config = config
        self.last_usage: dict[str, Any] | None = None

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return await self.generate_with_context(
            self.config.system_message or "", [{"role": "user", "content": prompt}], **kwargs
        )

    async def generate_with_context(
        self, system_message: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> str:
        return await asyncio.to_thread(self._request, system_message, messages, kwargs)

    def _request(self, system: str, messages: list[dict[str, str]], options: dict[str, Any]) -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("Set OPENAI_API_KEY before starting OpenEvolve")
        body = {
            "model": self.config.name,
            "instructions": system,
            "input": messages,
            "max_output_tokens": options.get("max_tokens", self.config.max_tokens),
            "reasoning": {"effort": getattr(self.config, "reasoning_effort", None) or "high"},
            "service_tier": "default",
            "store": False,
            "stream": True,
        }
        request = urllib.request.Request(
            (self.config.api_base or "https://api.openai.com/v1").rstrip("/") + "/responses",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        self.last_usage = None
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                value = _read_openai_stream(response)
        except Exception:
            record_usage(self.config.name, None)
            raise
        self.last_usage = value.get("usage")
        record_usage(self.config.name, self.last_usage)
        if value.get("status") != "completed":
            raise ValueError(f"OpenAI response not completed: {value.get('status', 'unknown')}")
        text = "".join(
            block["text"]
            for item in value.get("output", [])
            if item.get("type") == "message"
            for block in item.get("content", [])
            if block.get("type") == "output_text"
        )
        if not text.strip():
            raise ValueError("OpenAI returned no text")
        return text


def openai_client(config: Any) -> OpenAILLM:
    return OpenAILLM(config)


def credential_variable(backend: str) -> str:
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "compatible": "OPENAI_API_KEY",
    }[backend]


def compatible_client(config: Any) -> Any:
    variable = credential_variable(config.provider or "compatible")
    key = os.environ.get(variable)
    if not key:
        raise ValueError(f"Set {variable} before starting OpenEvolve")
    # The copy is used only by the client; OpenEvolve serializes the key-free original.
    cls = importlib.import_module("openevolve.llm.openai").OpenAILLM
    return cls(replace(config, api_key=key))


class ReplayLLM:
    """Offline test double. OpenEvolve itself and all circuit evaluations remain real."""

    last_usage = None

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        return await self.generate_with_context("", [{"role": "user", "content": prompt}])

    async def generate_with_context(
        self, system_message: str, messages: list[dict[str, str]], **kwargs: Any
    ) -> str:
        from qdiscover.toy_task.circuit import inverse_circuit

        fingerprint = hashlib.sha256(
            (system_message + json.dumps(messages, sort_keys=True)).encode()
        ).hexdigest()
        # OpenEvolve rejects a rewrite identical to its parent. Vary only this
        # comment deterministically so repeated/resumed smoke runs keep producing
        # candidates while evaluating the same known circuit.
        source = f"# Offline replay context: {fingerprint}\n" + inverse_circuit(anf=True)
        return "```python\n" + source + "```"


def replay_client(config: Any) -> ReplayLLM:
    return ReplayLLM()
