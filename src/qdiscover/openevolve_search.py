"""Real OpenEvolve engine, with task prompts, native Claude, and independent evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from qdiscover.api_cost import MODEL_RATES, USAGE_DIRECTORY_ENV, cost_summary
from qdiscover.artifacts import write_json
from qdiscover.catalog import UPSTREAM_COMMIT
from qdiscover.credentials import load_api_key
from qdiscover.evaluate import evaluate
from qdiscover.llm import parse_json_object
from qdiscover.openevolve_evaluator import admit_valid
from qdiscover.openevolve_llm import (
    anthropic_client,
    compatible_client,
    credential_variable,
    openai_client,
    replay_client,
)
from qdiscover.sandbox import SandboxConfig, ensure_available
from qdiscover.specification import parse_families, task_context

PINNED_VERSION = "0.4.1"
DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class OpenEvolveSettings:
    task: str
    backend: str = "anthropic"
    model: str = DEFAULT_MODEL
    api_base: str | None = None
    iterations: int = 100
    islands: int = 5
    workers: int = 3
    migration_interval: int = 10
    checkpoint_interval: int = 10
    seed: int = 0
    effort: str = "high"
    max_tokens: int = 32768
    model_timeout: int = 1200
    timeout: int = 3600
    jobs: int = 1
    kernel: str = "auto"
    smoke_test: bool = False
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)

    def __post_init__(self) -> None:
        if self.backend not in {"anthropic", "openai", "openrouter", "gemini", "compatible"}:
            raise ValueError("Unknown API backend")
        if self.effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unknown reasoning effort")
        if not self.model.strip():
            raise ValueError("A model ID is required")
        if (
            min(
                self.iterations,
                self.islands,
                self.workers,
                self.migration_interval,
                self.checkpoint_interval,
                self.max_tokens,
                self.model_timeout,
                self.timeout,
                self.jobs,
            )
            < 1
        ):
            raise ValueError("Counts, limits, and timeouts must be positive")
        if self.kernel not in {"auto", "c", "python"}:
            raise ValueError("Unknown kernel")
        if self.smoke_test and self.task != "toy-gf-inverse":
            raise ValueError("--smoke-test supports only toy-gf-inverse")
        if self.backend == "compatible" and not self.api_base:
            raise ValueError("--backend compatible requires --api-base")


def require_openevolve() -> None:
    try:
        version = importlib.metadata.version("openevolve")
    except importlib.metadata.PackageNotFoundError:
        raise RuntimeError("Install OpenEvolve with: uv sync --locked --extra openevolve") from None
    if version != PINNED_VERSION:
        raise RuntimeError(f"Expected openevolve=={PINNED_VERSION}; installed {version}")


def blank_source(family: str) -> str:
    return (
        f"# Algorithm family: {family}\n"
        "# EVOLVE-BLOCK-START\n"
        "raise NotImplementedError('Construct the required circuit and call Builder.emit()')\n"
        "# EVOLVE-BLOCK-END\n"
    )


def _llm_config(settings: OpenEvolveSettings) -> Any:
    types = importlib.import_module("openevolve.config")
    factory = anthropic_client if settings.backend == "anthropic" else compatible_client
    if settings.backend == "openai":
        factory = openai_client
    if settings.smoke_test:
        factory = replay_client
    api_base = settings.api_base or {
        "anthropic": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    }.get(settings.backend)
    return types.LLMConfig(
        provider=settings.backend,
        api_base=api_base,
        api_key=None,
        models=[
            types.LLMModelConfig(
                name=settings.model, init_client=factory, reasoning_effort=settings.effort
            )
        ],
        max_tokens=settings.max_tokens,
        timeout=settings.model_timeout,
        retries=0,
        temperature=None,
        random_seed=settings.seed,
    )


def build_config(
    settings: OpenEvolveSettings,
    out: Path,
    families: list[dict[str, str]],
    context: dict[str, Any] | None = None,
) -> Any:
    types = importlib.import_module("openevolve.config")
    system = (
        "Design a correct coherent reversible quantum circuit from the supplied specification. "
        "Minimize T*Q. Invalid candidates are rejected. Return a complete Python program in a "
        "python code fence. Include a short explanation of the idea before the code. "
        "Do not read published circuit implementations or modify the evaluator.\n\n"
        + json.dumps(
            context if context is not None else task_context(settings.task), ensure_ascii=False
        )
    )
    return types.Config(
        max_iterations=settings.iterations,
        random_seed=settings.seed,
        language="python",
        max_code_length=250000,
        diff_based_evolution=False,
        checkpoint_interval=settings.checkpoint_interval,
        checkpoint_on_improvement=True,
        llm=_llm_config(settings),
        prompt=types.PromptConfig(
            system_message=system,
            island_system_messages=[
                system + "\n\nYour algorithm family: " + json.dumps(f, ensure_ascii=False)
                for f in families
            ],
            num_top_programs=2,
            num_diverse_programs=2,
            use_template_stochasticity=False,
            include_artifacts=True,
        ),
        database=types.DatabaseConfig(
            num_islands=settings.islands,
            population_size=1000,
            archive_size=100,
            feature_dimensions=["toffoli", "qubits"],
            feature_bins={"toffoli": 20, "qubits": 20},
            migration_interval=settings.migration_interval,
            migration_rate=0.1,
            random_seed=settings.seed,
            island_initial_programs=[None]
            + [str(out / "seeds" / f"island_{i}.py") for i in range(1, settings.islands)],
        ),
        evaluator=types.EvaluatorConfig(
            timeout=settings.timeout + 30,
            max_retries=0,
            parallel_evaluations=settings.workers,
            cascade_evaluation=False,
            use_llm_feedback=False,
            enable_artifacts=True,
            evaluator_args={
                "task": settings.task,
                "out_dir": str(out / "evaluations"),
                "timeout": settings.timeout,
                "jobs": settings.jobs,
                "kernel": settings.kernel,
                "sandbox": asdict(settings.sandbox),
            },
        ),
        evolution_trace=types.EvolutionTraceConfig(
            enabled=True,
            include_code=True,
            include_prompts=True,
            include_failures=True,
            output_path=str(out / "evolution_trace.jsonl"),
        ),
    )


def ideate(
    settings: OpenEvolveSettings, out: Path, context: dict[str, Any]
) -> list[dict[str, str]]:
    if settings.smoke_test:
        families = [
            {
                "name": f"replay-{i}",
                "description": "Offline authored toy proposals; no model called",
            }
            for i in range(settings.islands)
        ]
    else:
        request = {
            **context,
            "stage": "ideation",
            "instruction": f"Propose {settings.islands} distinct algorithm families. Return only "
            'JSON: {"families": [{"name": str, "description": str}]}. No code yet.',
        }
        write_json(out / "ideation.request.json", request)
        ensemble_type = importlib.import_module("openevolve.llm.ensemble").LLMEnsemble

        async def generate() -> str:
            ensemble = ensemble_type(_llm_config(settings).models)
            return await ensemble.generate_with_context(
                system_message="Return the requested JSON object without Markdown.",
                messages=[{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
            )

        response = asyncio.run(generate())
        (out / "ideation.response.txt").write_text(response)
        families = parse_json_object(response).get("families")
    families = parse_families({"families": families}, settings.islands)
    write_json(out / "families.json", families)
    return families


def run_openevolve(
    settings: OpenEvolveSettings,
    out: Path,
    *,
    prepare_only: bool = False,
    resume: bool = False,
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    require_openevolve()
    context = task_context(settings.task)  # Validate before writes or model requests.
    context_hash = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    out = out.resolve()
    metadata = out / "run_settings.json"
    continuing = resume or checkpoint is not None
    if prepare_only and continuing:
        raise ValueError("Use --prepare-only for a new run; resume starts the saved run")
    if metadata.exists():
        previous = json.loads(metadata.read_text())
        if continuing:
            if previous["task_context_sha256"] != context_hash:
                raise ValueError("Cannot resume with a changed task specification")
            for key, value in asdict(settings).items():
                if key != "iterations" and previous["settings"].get(key) != value:
                    raise ValueError(f"Cannot resume with a different {key}")
        elif previous["status"] != "prepared":
            checkpoints = list((out / "engine" / "checkpoints").glob("checkpoint_*"))
            if previous["status"] != "failed" or checkpoints:
                raise ValueError("Run exists; use --resume or a new --out directory")
    elif continuing:
        raise ValueError("No run_settings.json to resume in this output directory")
    if continuing:
        if checkpoint is None:
            candidates = list((out / "engine" / "checkpoints").glob("checkpoint_*"))
            if not candidates:
                raise ValueError("No OpenEvolve checkpoint is available")
            checkpoint = max(candidates, key=lambda p: int(p.name.rsplit("_", 1)[1]))
        checkpoint = checkpoint.resolve()
        if not checkpoint.is_dir() or not (checkpoint / "metadata.json").is_file():
            raise ValueError("Not an OpenEvolve checkpoint directory")
    if not prepare_only and not settings.smoke_test:
        variable = credential_variable(settings.backend)
        load_api_key(variable)
        if not os.environ.get(variable):
            raise ValueError(
                f"Set {variable} in .env or the environment; "
                "use --prepare-only to inspect without an API key"
            )
    if not prepare_only:
        ensure_available(settings.sandbox)
    out.mkdir(parents=True, exist_ok=True)
    plan = {
        "status": "prepared" if prepare_only else "running",
        "engine": f"openevolve=={PINNED_VERSION}",
        "settings": asdict(settings),
        "upstream_commit": UPSTREAM_COMMIT,
        "task_context_sha256": context_hash,
        "credential_environment_variable": credential_variable(settings.backend),
        "paper_equivalence": "Search-method reconstruction; original prompts/settings not released",
    }
    write_json(metadata, plan)
    if prepare_only:
        write_json(out / "task_context.json", context)
        return plan
    track_cost = (
        settings.backend in {"anthropic", "openai"}
        and settings.model in MODEL_RATES
        and not settings.smoke_test
    )
    usage_session = out / "api_usage" / uuid.uuid4().hex
    previous_usage_directory = os.environ.get(USAGE_DIRECTORY_ENV)
    if track_cost:
        os.environ[USAGE_DIRECTORY_ENV] = str(usage_session)
    try:
        plan.update(_run_engine(settings, out, continuing, checkpoint, context))
    except Exception as exc:
        plan.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    except KeyboardInterrupt:
        plan.update(status="interrupted")
        raise
    finally:
        if track_cost:
            if previous_usage_directory is None:
                os.environ.pop(USAGE_DIRECTORY_ENV, None)
            else:
                os.environ[USAGE_DIRECTORY_ENV] = previous_usage_directory
            cost = cost_summary(usage_session, settings.model)
            plan["api_cost"] = cost
            write_json(out / "api_cost.json", cost)
            print(
                "API cost estimate (USD): "
                f"this run ${cost['current_run']['estimated_cost_usd']:.6f}; "
                f"cumulative ${cost['cumulative']['estimated_cost_usd']:.6f}",
                file=sys.stderr,
            )
            if cost["cumulative"]["requests_without_usage"]:
                print(
                    "Usage unavailable for some requests; estimate is incomplete.", file=sys.stderr
                )
        write_json(metadata, plan)
        write_json(out / "summary.json", plan)
    return plan


def _run_engine(
    settings: OpenEvolveSettings,
    out: Path,
    continuing: bool,
    checkpoint: Path | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if continuing:
        families = json.loads((out / "families.json").read_text())
    else:
        families = ideate(settings, out, context)
        for i, family in enumerate(families):
            source = blank_source(family["name"])
            path = out / "seeds" / f"island_{i}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
    config = build_config(settings, out, families, context)
    api = importlib.import_module("openevolve")
    population_type = importlib.import_module("openevolve.population").PopulationStrategy
    result = api.run_evolution(
        initial_program=out / "seeds" / "island_0.py",
        evaluator=Path(__file__).with_name("openevolve_evaluator.py"),
        config=config,
        output_dir=str(out / "engine"),
        cleanup=False,
        checkpoint_path=str(checkpoint) if checkpoint else None,
        population_strategy=population_type(admit=admit_valid),
    )
    best_valid = result.metrics.get("valid") == 1.0
    final = None
    if best_valid:
        best = out / "best_circuit.py"
        best.write_text(result.best_code)
        final = evaluate(
            settings.task,
            best,
            out / "best_evaluation",
            timeout=settings.timeout,
            jobs=settings.jobs,
            kernel=settings.kernel,
            sandbox=settings.sandbox,
        )
        best_valid = final.valid
    return {
        "status": "completed" if best_valid else "no-valid-circuit",
        "best_valid": best_valid,
        "best_metrics": result.metrics,
        "final_evaluation": asdict(final) if final else None,
    }
