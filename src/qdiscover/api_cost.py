"""Durable, per-response usage records shared by OpenEvolve worker processes."""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from qdiscover.artifacts import write_json

USAGE_DIRECTORY_ENV = "QDISCOVER_API_USAGE_DIRECTORY"
# Standard global Claude API prices, USD per million tokens, checked 2026-11-09.
PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
OPUS_RATES = {
    "input_tokens": "4",
    "output_tokens": "20",
    "cache_creation_5m_input_tokens": "5",
    "cache_creation_1h_input_tokens": "8",
    "cache_read_input_tokens": "0.20",
}
MODEL_RATES = {
    # Standard global Fable API prices, checked 2026-11-10.
    "claude-fable-5-2": dict(zip(OPUS_RATES, ("8", "40", "10", "16", "0.20"), strict=True)),
    "claude-opus-5-5": OPUS_RATES,
    "claude-sonnet-5-5": dict(zip(OPUS_RATES, ("2", "10", "2.5", "4", "0.10"), strict=True)),
    "claude-haiku-5-5": dict(
        zip(OPUS_RATES, ("0.10", "0.50", "0.125", "0.20", "0.01"), strict=True)
    ),
}
HAIKU_LONG_RATES = dict(zip(OPUS_RATES, ("0.50", "2.50", "0.625", "1", "0.05"), strict=True))
OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
OPENAI_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_30m_input_tokens",
    "cache_creation_12h_input_tokens",
)
OPENAI_RATES = {
    model: dict(zip(OPENAI_TOKEN_KEYS, values, strict=True))
    for model, values in {
        "gpt-6.1-sol": ("2", "10", "0.10", "2.50", "5"),
        "gpt-6.1-terra": ("1", "5", "0.05", "1.25", "2.50"),
        "gpt-6-luna": ("0.10", "0.50", "0.01", "0.125", "0.25"),
    }.items()
}
MODEL_RATES.update(OPENAI_RATES)


def record_usage(model: str, usage: dict[str, Any] | None) -> None:
    directory = os.environ.get(USAGE_DIRECTORY_ENV)
    if directory:
        # Separate atomic files avoid lost updates across threads and processes.
        write_json(Path(directory) / f"{uuid.uuid4().hex}.json", {"model": model, "usage": usage})


def usage_totals(paths: list[Path]) -> dict[str, Any]:
    tokens = dict.fromkeys((*OPUS_RATES, *OPENAI_TOKEN_KEYS), 0)
    cost = Decimal(0)
    missing = 0
    for path in paths:
        record = json.loads(path.read_text())
        usage = record.get("usage")
        rates = MODEL_RATES.get(record["model"])
        if rates is None or not isinstance(usage, dict):
            missing += 1
            continue
        if not all(isinstance(usage.get(k), int) for k in ("input_tokens", "output_tokens")):
            missing += 1
            continue
        if record["model"] in OPENAI_RATES:
            details = usage.get("input_tokens_details") or {}
            reads = details.get("cached_tokens", 0)
            writes = details.get("cache_write_tokens", 0)
            lifetimes = details.get("cache_write_tokens_details") or {}
            long_writes = lifetimes.get("ttl_12h_tokens", 0)
            request_tokens = {
                "input_tokens": usage["input_tokens"] - reads - writes,
                "output_tokens": usage["output_tokens"],
                "cache_read_input_tokens": reads,
                "cache_creation_30m_input_tokens": writes - long_writes,
                "cache_creation_12h_input_tokens": long_writes,
            }
            for key, count in request_tokens.items():
                multiplier = Decimal(1)
                if usage["input_tokens"] > 272_000:
                    multiplier = Decimal("1.5") if key == "output_tokens" else Decimal(2)
                tokens[key] += count
                cost += Decimal(count) * Decimal(rates[key]) * multiplier
            continue
        request_tokens = dict.fromkeys(OPUS_RATES, 0)
        request_tokens["input_tokens"] = usage["input_tokens"]
        request_tokens["output_tokens"] = usage["output_tokens"]
        request_tokens["cache_read_input_tokens"] = usage.get("cache_read_input_tokens", 0)
        cache = usage.get("cache_creation") or {}
        hour = cache.get("ephemeral_1h_input_tokens", 0)
        five = cache.get("ephemeral_5m_input_tokens", 0)
        total_cache = usage.get("cache_creation_input_tokens", five + hour)
        # Older response shapes only expose the total; default cache TTL is five minutes.
        request_tokens["cache_creation_1h_input_tokens"] = hour
        request_tokens["cache_creation_5m_input_tokens"] = total_cache - hour
        prompt_tokens = sum(v for k, v in request_tokens.items() if k != "output_tokens")
        if record["model"] == "claude-haiku-5-5" and prompt_tokens > 100_000:
            rates = HAIKU_LONG_RATES
        for key, count in request_tokens.items():
            tokens[key] += count
            cost += Decimal(count) * Decimal(rates[key])
    return {
        "requests": len(paths),
        "requests_without_usage": missing,
        "tokens": tokens,
        "estimated_cost_usd": float(cost / Decimal(1_000_000)),
    }


def cost_summary(session: Path, model: str = "claude-opus-5-5") -> dict[str, Any]:
    return {
        "model": model,
        "currency": "USD",
        "pricing_checked_on": "2026-11-10",
        "pricing_source": OPENAI_PRICING_SOURCE if model in OPENAI_RATES else PRICING_SOURCE,
        "usd_per_million_tokens": MODEL_RATES[model],
        "haiku_long_context": {
            "prompt_tokens_over": 100_000,
            "usd_per_million_tokens": HAIKU_LONG_RATES,
        }
        if model == "claude-haiku-5-5"
        else None,
        "openai_long_context": {
            "prompt_tokens_over": 272_000,
            "input_and_cache_multiplier": 2,
            "output_multiplier": 1.5,
        }
        if model in OPENAI_RATES
        else None,
        "current_run": usage_totals(list(session.glob("*.json"))),
        "cumulative": usage_totals(list(session.parent.glob("*/*.json"))),
        "note": "Estimate for recorded responses at standard API rates; excludes discounts, taxes "
        "and any charges for requests whose usage was not received. Earlier untracked runs "
        "are not included.",
    }
