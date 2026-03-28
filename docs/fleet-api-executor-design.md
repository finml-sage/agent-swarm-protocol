# Fleet-API Executor Design: Multi-Step Pipeline Architecture

**Status**: Draft (research deliverable)
**Author**: Nexus (nexus-marbell)
**Date**: 2026-03-17
**Depends on**: RFC 0 (Principal Orchestrator Pattern), RFC 1 (Agentic Task API), RFC 2 (Pi.dev Sub-Agent Architecture)
**Driven by**: Dan's directive on deterministic pipelines, multi-model routing, and per-workflow cost optimization

---

## 1. Problem

The current fleet-api executor (`LocalExecutor` in `src/fleet_agent/executor.py`) dispatches tasks as single-shot subprocess calls. It passes task input as JSON on stdin and reads newline-delimited JSON events from stdout. This is a one-step execution model: one command, one result.

Dan's directive requires three capabilities this model cannot provide:

1. **Deterministic pipelines with gates**: Step 1 -> validation gate -> Step 2 -> quality gate -> Step 3. Pure code gates between LLM steps. The harness ENFORCES sequence, not just guides.
2. **Multi-model routing per step**: Each step uses the optimal model. Research: Haiku for extraction, Sonnet for synthesis, Opus for judgment. Agent reflections: Opus (analyze) -> Mercury-2 (dream) -> Opus (observe).
3. **Per-workflow cost optimization**: Each step gets exactly the context it needs. A 10-step workflow might use 5 different models and never exceed 8K tokens per step.

The graduation pattern: **rules shape judgment -> hooks enforce actions -> HARNESS ENFORCES WORKFLOW**.

---

## 2. Architecture Overview

The executor becomes a **pipeline runner** that interprets workflow step definitions and executes them in sequence, with gates between steps.

```
Fleet Agent Sidecar
  |
  +-- Poller (GET /agents/{id}/tasks/pending)
  |
  +-- PipelineExecutor (replaces LocalExecutor)
        |
        +-- StepRunner
        |     +-- LLMStep (calls Anthropic, xAI, Inception, MiniMax APIs)
        |     +-- CodeStep (runs Python functions -- gates, validators, transformers)
        |     +-- ToolStep (executes shell commands, file operations)
        |
        +-- GateRunner
        |     +-- SchemaGate (JSON Schema validation)
        |     +-- ThresholdGate (numeric checks)
        |     +-- CustomGate (arbitrary Python predicate)
        |
        +-- ModelRouter
        |     +-- AnthropicProvider (Haiku, Sonnet, Opus)
        |     +-- InceptionProvider (Mercury-2)
        |     +-- XAIProvider (Grok 4, Grok 4.1 Fast)
        |     +-- MiniMaxProvider (M2, M2.5)
        |     +-- OpenAICompatProvider (any OpenAI-format API)
        |
        +-- ContextManager
              +-- Per-step context assembly
              +-- Cross-step result forwarding
              +-- Token budget enforcement
```

---

## 3. Workflow Step Definition Schema

Workflows gain a `steps` field in their registration. This is the pipeline definition.

### 3.1 Step Types

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepType(Enum):
    """The three kinds of pipeline steps."""
    LLM = "llm"      # Call a language model
    CODE = "code"     # Run a Python function (gate, transform, validate)
    TOOL = "tool"     # Execute a shell command or file operation


class GateAction(Enum):
    """What happens when a gate check fails."""
    FAIL = "fail"       # Abort the pipeline with error
    RETRY = "retry"     # Re-run the previous step (with feedback)
    SKIP = "skip"       # Skip to the next step


@dataclass(frozen=True)
class StepDefinition:
    """A single step in a workflow pipeline."""
    id: str                          # Unique within the workflow (e.g., "extract", "validate", "synthesize")
    type: StepType                   # What kind of step
    description: str                 # Human-readable purpose

    # LLM step fields
    model: str | None = None         # Model identifier (e.g., "opus", "mercury-2", "haiku")
    system_prompt: str | None = None # System prompt for the LLM call
    user_prompt_template: str | None = None  # Template with {input}, {prev_result}, {context} placeholders
    max_tokens: int = 4096           # Max output tokens for LLM call
    temperature: float = 0.0         # Temperature for LLM call

    # Code step fields
    function: str | None = None      # Dotted path to Python function (e.g., "mymodule.validate_output")

    # Tool step fields
    command: str | None = None       # Shell command template

    # Gate (applied after this step completes, before next step starts)
    gate: GateDefinition | None = None

    # Context control
    input_from: list[str] = field(default_factory=list)  # Step IDs whose results feed this step
    max_input_tokens: int | None = None  # Token budget for assembled input


@dataclass(frozen=True)
class GateDefinition:
    """A deterministic check between pipeline steps."""
    type: str                        # "schema", "threshold", "custom"
    spec: dict[str, Any] = field(default_factory=dict)
    on_fail: GateAction = GateAction.FAIL
    max_retries: int = 2             # Only applies when on_fail is RETRY
    feedback_template: str | None = None  # Feedback to inject on retry


@dataclass(frozen=True)
class PipelineDefinition:
    """The full pipeline for a workflow."""
    steps: list[StepDefinition]
    default_model: str = "sonnet"    # Fallback when step.model is None
    max_total_cost_usd: float | None = None  # Budget cap for the entire pipeline
```

### 3.2 Example: Agent Reflections Pipeline

This is the first candidate workflow. Currently implemented as three sequential `urllib.request` calls in `agent_reflections/mercury.py`. The harness version adds gates and allows per-step model routing.

```yaml
id: agent-reflections
name: "Agent Reflections"
steps:
  - id: gather-context
    type: code
    description: "Assemble context from session files and memory sources"
    function: "agent_reflections.context.assemble_context"
    gate:
      type: threshold
      spec:
        field: "fragment_count"
        min: 3
      on_fail: fail

  - id: layer-1-conflict
    type: llm
    description: "Analyze problem against context fragments (silent output)"
    model: "opus"
    system_prompt: "{LAYER_1_SYSTEM_PROMPT}"
    user_prompt_template: "PROBLEM: {input.problem}\n\nCONTEXT FRAGMENTS:\n{prev_result}"
    max_tokens: 2048
    temperature: 0.0
    input_from: ["gather-context"]
    gate:
      type: threshold
      spec:
        field: "output_length"
        min: 100
      on_fail: retry
      max_retries: 1
      feedback_template: "Your conflict model was too short. Elaborate on the tensions."

  - id: layer-2-dream
    type: llm
    description: "Render the conflict as a vivid scene (third person)"
    model: "mercury-2"
    system_prompt: "{LAYER_2_SYSTEM_PROMPT}"
    user_prompt_template: "{prev_result}"
    max_tokens: 2048
    temperature: 0.7
    input_from: ["layer-1-conflict"]
    gate:
      type: threshold
      spec:
        field: "output_length"
        min: 200
      on_fail: retry

  - id: layer-3-observer
    type: llm
    description: "Return to first person, decode the dream"
    model: "opus"
    system_prompt: "{LAYER_3_SYSTEM_PROMPT}"
    user_prompt_template: "MY PROBLEM:\n{input.problem}\n\nTHE DREAM:\n{prev_result}"
    max_tokens: 2048
    temperature: 0.3
    input_from: ["layer-2-dream"]
```

### 3.3 Example: Static Analysis Pipeline

```yaml
id: static-analysis
name: "Full Static Analysis Scan"
steps:
  - id: pyscn-scan
    type: tool
    description: "Run pyscn health scan"
    command: "pyscn analyze {input.repo_path} --json"
    gate:
      type: schema
      spec:
        required: ["health_score", "grade"]
      on_fail: fail

  - id: deepcsim-scan
    type: tool
    description: "Run DeepCSIM duplication scan"
    command: "deepcsim-cli {input.repo_path} --threshold 60 --json"

  - id: synthesize
    type: llm
    description: "Synthesize scan results into actionable report"
    model: "sonnet"
    system_prompt: "You are a code quality analyst. Synthesize scan results into a prioritized action list."
    user_prompt_template: "pyscn results:\n{results.pyscn-scan}\n\nDeepCSIM results:\n{results.deepcsim-scan}"
    max_tokens: 4096
    input_from: ["pyscn-scan", "deepcsim-scan"]
    gate:
      type: schema
      spec:
        required: ["priority_items"]
      on_fail: retry
      feedback_template: "Output must include a 'priority_items' list."
```

---

## 4. Model Router

The model router resolves a model alias (e.g., `"opus"`, `"mercury-2"`, `"haiku"`) to an API provider and makes the actual call.

### 4.1 Provider Interface

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMRequest:
    """Normalized request for any LLM provider."""
    system_prompt: str
    user_message: str
    model: str               # Provider-specific model ID
    max_tokens: int = 4096
    temperature: float = 0.0
    tools: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response from any LLM provider."""
    content: str
    model: str               # Actual model used
    input_tokens: int
    output_tokens: int
    cost_usd: float          # Estimated cost of this call
    stop_reason: str
    tool_calls: list[dict[str, Any]] | None = None


class LLMProvider(ABC):
    """Base class for LLM API providers."""

    @abstractmethod
    async def call(self, request: LLMRequest) -> LLMResponse:
        """Make a single LLM API call and return the response."""
        ...

    @abstractmethod
    def supports_model(self, model_alias: str) -> bool:
        """Return True if this provider handles the given model alias."""
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Estimate cost in USD for a call with the given token counts."""
        ...
```

### 4.2 Provider Implementations

```python
class AnthropicProvider(LLMProvider):
    """Anthropic API (Haiku, Sonnet, Opus)."""

    MODEL_MAP = {
        "haiku": "claude-haiku-4-5-20250514",
        "sonnet": "claude-sonnet-4-20250514",
        "opus": "claude-opus-4-20250514",
    }

    PRICING = {  # per million tokens (input, output)
        "haiku": (1.00, 5.00),
        "sonnet": (3.00, 15.00),
        "opus": (15.00, 75.00),
    }

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def call(self, request: LLMRequest) -> LLMResponse:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.user_message}],
        )
        content = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=self.estimate_cost(
                response.usage.input_tokens,
                response.usage.output_tokens,
                request.model,
            ),
            stop_reason=response.stop_reason or "end_turn",
        )

    def supports_model(self, model_alias: str) -> bool:
        return model_alias in self.MODEL_MAP

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        # Reverse-lookup alias from model ID
        alias = next((k for k, v in self.MODEL_MAP.items() if v == model), None)
        if alias is None:
            return 0.0
        inp_rate, out_rate = self.PRICING[alias]
        return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


class InceptionProvider(LLMProvider):
    """Inception Labs API (Mercury-2). OpenAI-compatible format."""

    MODEL_MAP = {"mercury-2": "mercury-2"}
    PRICING = {"mercury-2": (0.25, 0.75)}  # per million tokens

    def __init__(self, api_key: str, base_url: str = "https://api.inceptionlabs.ai/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def call(self, request: LLMRequest) -> LLMResponse:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": request.model,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ],
                    "max_tokens": request.max_tokens,
                    "temperature": max(0.5, request.temperature),  # Mercury range: 0.5-1.0
                },
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", request.model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=self.estimate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                request.model,
            ),
            stop_reason=data["choices"][0].get("finish_reason", "stop"),
        )

    def supports_model(self, model_alias: str) -> bool:
        return model_alias in self.MODEL_MAP

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        inp_rate, out_rate = self.PRICING.get(model, (0.25, 0.75))
        return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


class OpenAICompatProvider(LLMProvider):
    """Generic OpenAI-compatible API provider (xAI, MiniMax, etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_map: dict[str, str],
        pricing: dict[str, tuple[float, float]],
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model_map = model_map
        self._pricing = pricing

    async def call(self, request: LLMRequest) -> LLMResponse:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": request.model,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.user_message},
                    ],
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", request.model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            cost_usd=self.estimate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                request.model,
            ),
            stop_reason=data["choices"][0].get("finish_reason", "stop"),
        )

    def supports_model(self, model_alias: str) -> bool:
        return model_alias in self._model_map

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        alias = next((k for k, v in self._model_map.items() if v == model), model)
        inp_rate, out_rate = self._pricing.get(alias, (0.0, 0.0))
        return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000
```

### 4.3 Router

```python
class ModelRouter:
    """Routes model aliases to providers and makes calls."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = providers

    def resolve(self, model_alias: str) -> LLMProvider:
        """Find the provider that handles this model alias."""
        for provider in self._providers:
            if provider.supports_model(model_alias):
                return provider
        raise ValueError(
            f"No provider registered for model '{model_alias}'. "
            f"Available: {self._available_models()}"
        )

    def _available_models(self) -> list[str]:
        models = []
        for p in self._providers:
            if hasattr(p, '_model_map'):
                models.extend(p._model_map.keys())
            elif hasattr(p, 'MODEL_MAP'):
                models.extend(p.MODEL_MAP.keys())
        return models

    async def call(self, model_alias: str, request: LLMRequest) -> LLMResponse:
        """Resolve model alias and make the API call."""
        provider = self.resolve(model_alias)
        # Resolve alias to provider-specific model ID
        if hasattr(provider, 'MODEL_MAP'):
            model_id = provider.MODEL_MAP.get(model_alias, model_alias)
        elif hasattr(provider, '_model_map'):
            model_id = provider._model_map.get(model_alias, model_alias)
        else:
            model_id = model_alias
        resolved_request = LLMRequest(
            system_prompt=request.system_prompt,
            user_message=request.user_message,
            model=model_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            tools=request.tools,
        )
        return await provider.call(resolved_request)
```

---

## 5. Pipeline Executor

The `PipelineExecutor` replaces `LocalExecutor`. It interprets the `PipelineDefinition` and executes steps in sequence, running gates between steps.

### 5.1 Execution Loop

```python
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import subprocess
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of executing a single pipeline step."""
    step_id: str
    output: Any
    tokens_used: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None
    retries: int = 0


@dataclass
class PipelineState:
    """Accumulated state across pipeline execution."""
    results: dict[str, StepResult] = field(default_factory=dict)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    current_step_index: int = 0


class PipelineExecutor:
    """Executes multi-step workflows with gates and multi-model routing."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def execute(
        self,
        pipeline: PipelineDefinition,
        task_input: dict[str, Any],
    ) -> AsyncGenerator[TaskEvent, None]:
        """Execute a pipeline and yield events as they occur."""
        state = PipelineState()
        sequence = 0

        for i, step in enumerate(pipeline.steps):
            state.current_step_index = i
            sequence += 1
            yield TaskEvent(
                event_type="progress",
                data={
                    "step_id": step.id,
                    "step_index": i,
                    "total_steps": len(pipeline.steps),
                    "description": step.description,
                    "status": "starting",
                },
                sequence=sequence,
            )

            # Execute the step (with retry logic if gate fails)
            try:
                result = await self._execute_step_with_gate(
                    step=step,
                    pipeline=pipeline,
                    task_input=task_input,
                    state=state,
                )
            except PipelineError as exc:
                sequence += 1
                yield TaskEvent(
                    event_type="failed",
                    data={
                        "error": str(exc),
                        "failed_step": step.id,
                        "step_index": i,
                    },
                    sequence=sequence,
                )
                return

            # Record result
            state.results[step.id] = result
            state.total_tokens += result.tokens_used
            state.total_cost_usd += result.cost_usd

            # Check budget
            if pipeline.max_total_cost_usd and state.total_cost_usd > pipeline.max_total_cost_usd:
                sequence += 1
                yield TaskEvent(
                    event_type="failed",
                    data={
                        "error": "BUDGET_EXCEEDED",
                        "detail": (
                            f"Pipeline cost ${state.total_cost_usd:.4f} "
                            f"exceeds budget ${pipeline.max_total_cost_usd:.4f}"
                        ),
                        "completed_steps": list(state.results.keys()),
                    },
                    sequence=sequence,
                )
                return

            sequence += 1
            yield TaskEvent(
                event_type="progress",
                data={
                    "step_id": step.id,
                    "status": "completed",
                    "tokens_used": result.tokens_used,
                    "cost_usd": result.cost_usd,
                    "model_used": result.model_used,
                },
                sequence=sequence,
            )

        # Pipeline complete
        sequence += 1
        final_step_id = pipeline.steps[-1].id
        yield TaskEvent(
            event_type="completed",
            data={
                "result": state.results[final_step_id].output,
                "total_tokens": state.total_tokens,
                "total_cost_usd": state.total_cost_usd,
                "steps_completed": len(pipeline.steps),
                "step_results": {
                    sid: {"output_preview": str(r.output)[:200], "cost_usd": r.cost_usd}
                    for sid, r in state.results.items()
                },
            },
            sequence=sequence,
        )

    async def _execute_step_with_gate(
        self,
        step: StepDefinition,
        pipeline: PipelineDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
    ) -> StepResult:
        """Execute a step and validate its gate. Retry if gate allows."""
        max_attempts = 1 + (step.gate.max_retries if step.gate and step.gate.on_fail == GateAction.RETRY else 0)
        last_error: str | None = None

        for attempt in range(max_attempts):
            # Build feedback for retries
            feedback = None
            if attempt > 0 and step.gate and step.gate.feedback_template:
                feedback = step.gate.feedback_template

            result = await self._execute_step(
                step=step,
                pipeline=pipeline,
                task_input=task_input,
                state=state,
                retry_feedback=feedback,
            )

            # Run gate if defined
            if step.gate is not None:
                gate_passed, gate_error = self._check_gate(step.gate, result.output)
                if not gate_passed:
                    last_error = gate_error
                    if step.gate.on_fail == GateAction.FAIL:
                        raise PipelineError(
                            f"Gate failed on step '{step.id}': {gate_error}"
                        )
                    elif step.gate.on_fail == GateAction.SKIP:
                        logger.warning("Gate failed on step '%s', skipping: %s", step.id, gate_error)
                        result = StepResult(step_id=step.id, output=None)
                        break
                    elif step.gate.on_fail == GateAction.RETRY:
                        if attempt < max_attempts - 1:
                            logger.info(
                                "Gate failed on step '%s' (attempt %d/%d), retrying: %s",
                                step.id, attempt + 1, max_attempts, gate_error,
                            )
                            result = StepResult(
                                step_id=step.id,
                                output=result.output,
                                retries=attempt + 1,
                            )
                            continue
                        else:
                            raise PipelineError(
                                f"Gate failed on step '{step.id}' after {max_attempts} attempts: {gate_error}"
                            )
            # Gate passed or no gate
            result = StepResult(
                step_id=step.id,
                output=result.output,
                tokens_used=result.tokens_used,
                cost_usd=result.cost_usd,
                model_used=result.model_used,
                retries=attempt,
            )
            break

        return result

    async def _execute_step(
        self,
        step: StepDefinition,
        pipeline: PipelineDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
        retry_feedback: str | None = None,
    ) -> StepResult:
        """Execute a single step based on its type."""
        if step.type == StepType.LLM:
            return await self._execute_llm_step(step, pipeline, task_input, state, retry_feedback)
        elif step.type == StepType.CODE:
            return await self._execute_code_step(step, task_input, state)
        elif step.type == StepType.TOOL:
            return await self._execute_tool_step(step, task_input, state)
        else:
            raise PipelineError(f"Unknown step type: {step.type}")

    async def _execute_llm_step(
        self,
        step: StepDefinition,
        pipeline: PipelineDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
        retry_feedback: str | None,
    ) -> StepResult:
        """Execute an LLM step via the model router."""
        model_alias = step.model or pipeline.default_model

        # Assemble input context from previous steps
        context = self._assemble_context(step, task_input, state)

        # Build user message from template
        user_message = self._render_template(
            step.user_prompt_template or "{context}",
            task_input=task_input,
            context=context,
            state=state,
        )

        if retry_feedback:
            user_message = f"{user_message}\n\nFEEDBACK FROM PREVIOUS ATTEMPT:\n{retry_feedback}"

        request = LLMRequest(
            system_prompt=step.system_prompt or "",
            user_message=user_message,
            model=model_alias,  # Router resolves this
            max_tokens=step.max_tokens,
            temperature=step.temperature,
        )

        response = await self._router.call(model_alias, request)

        return StepResult(
            step_id=step.id,
            output=response.content,
            tokens_used=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
            model_used=response.model,
        )

    async def _execute_code_step(
        self,
        step: StepDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
    ) -> StepResult:
        """Execute a Python function step."""
        if not step.function:
            raise PipelineError(f"Code step '{step.id}' missing 'function' field")

        module_path, func_name = step.function.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)

        # Pass task input and previous results
        result = func(task_input, {k: v.output for k, v in state.results.items()})

        # Support both sync and async functions
        if asyncio.iscoroutine(result):
            result = await result

        return StepResult(step_id=step.id, output=result)

    async def _execute_tool_step(
        self,
        step: StepDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
    ) -> StepResult:
        """Execute a shell command step."""
        if not step.command:
            raise PipelineError(f"Tool step '{step.id}' missing 'command' field")

        command = self._render_template(step.command, task_input, "", state)

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise PipelineError(
                f"Tool step '{step.id}' command failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )

        output = stdout.decode(errors="replace").strip()
        # Try to parse as JSON
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            pass  # Keep as string

        return StepResult(step_id=step.id, output=output)

    def _assemble_context(
        self,
        step: StepDefinition,
        task_input: dict[str, Any],
        state: PipelineState,
    ) -> str:
        """Assemble context for a step from its input_from references."""
        if not step.input_from:
            # Default: use the immediately previous step's output
            if state.results:
                last_key = list(state.results.keys())[-1]
                return str(state.results[last_key].output)
            return json.dumps(task_input)

        parts = []
        for source_id in step.input_from:
            if source_id in state.results:
                parts.append(str(state.results[source_id].output))
            else:
                logger.warning("Step '%s' references unknown source '%s'", step.id, source_id)
        return "\n\n---\n\n".join(parts)

    def _render_template(
        self,
        template: str,
        task_input: dict[str, Any],
        context: str | Any,
        state: PipelineState,
    ) -> str:
        """Simple template rendering with {input.*}, {prev_result}, {context}, {results.*}."""
        result = template
        result = result.replace("{context}", str(context))

        # {prev_result} = output of the immediately previous step
        if state.results:
            last_key = list(state.results.keys())[-1]
            result = result.replace("{prev_result}", str(state.results[last_key].output))

        # {input.field} = task input field
        result = result.replace("{input}", json.dumps(task_input))
        for key, value in task_input.items():
            result = result.replace(f"{{input.{key}}}", str(value))

        # {results.step_id} = output of a specific step
        for step_id, step_result in state.results.items():
            result = result.replace(f"{{results.{step_id}}}", str(step_result.output))

        return result

    def _check_gate(
        self,
        gate: GateDefinition,
        output: Any,
    ) -> tuple[bool, str | None]:
        """Run a gate check. Returns (passed, error_message)."""
        if gate.type == "schema":
            return self._check_schema_gate(gate.spec, output)
        elif gate.type == "threshold":
            return self._check_threshold_gate(gate.spec, output)
        elif gate.type == "custom":
            return self._check_custom_gate(gate.spec, output)
        else:
            raise PipelineError(f"Unknown gate type: {gate.type}")

    def _check_schema_gate(self, spec: dict[str, Any], output: Any) -> tuple[bool, str | None]:
        """Check that output contains required fields."""
        required = spec.get("required", [])
        if isinstance(output, dict):
            missing = [f for f in required if f not in output]
            if missing:
                return False, f"Missing required fields: {missing}"
            return True, None
        elif isinstance(output, str):
            # For string outputs, check if required keys appear as substrings
            missing = [f for f in required if f not in output]
            if missing:
                return False, f"Output text missing expected content: {missing}"
            return True, None
        return False, f"Expected dict or str, got {type(output).__name__}"

    def _check_threshold_gate(self, spec: dict[str, Any], output: Any) -> tuple[bool, str | None]:
        """Check numeric thresholds on output."""
        field_name = spec.get("field", "")

        if field_name == "output_length":
            value = len(str(output))
        elif isinstance(output, dict) and field_name in output:
            value = output[field_name]
        else:
            return False, f"Cannot extract field '{field_name}' from output"

        min_val = spec.get("min")
        max_val = spec.get("max")

        if min_val is not None and value < min_val:
            return False, f"{field_name}={value} below minimum {min_val}"
        if max_val is not None and value > max_val:
            return False, f"{field_name}={value} above maximum {max_val}"
        return True, None

    def _check_custom_gate(self, spec: dict[str, Any], output: Any) -> tuple[bool, str | None]:
        """Run a custom Python predicate."""
        func_path = spec.get("function")
        if not func_path:
            raise PipelineError("Custom gate requires 'function' in spec")

        module_path, func_name = func_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)

        result = func(output)
        if isinstance(result, tuple):
            return result  # (bool, str | None)
        return bool(result), None if result else "Custom gate check failed"


class PipelineError(Exception):
    """Raised when pipeline execution encounters a non-recoverable error."""
```

---

## 6. Integration with Fleet-API

### 6.1 Workflow Registration Extension

The `Workflow` model gains a `pipeline` JSONB column that stores the `PipelineDefinition` serialized as JSON.

```sql
ALTER TABLE workflows ADD COLUMN pipeline JSONB;
```

When `pipeline` is NULL, the workflow uses the legacy single-shot `LocalExecutor`. When `pipeline` is present, the `PipelineExecutor` is used. This is backward compatible.

### 6.2 Sidecar Configuration Extension

```python
class SidecarConfig(BaseSettings):
    # ... existing fields ...

    # Multi-model API keys (all optional -- only needed for models the workflow uses)
    anthropic_api_key: str | None = None
    inception_api_key: str | None = None
    xai_api_key: str | None = None
    minimax_api_key: str | None = None

    # Custom OpenAI-compatible providers (JSON: {"alias": {"base_url": "...", "api_key_env": "...", "models": {...}}})
    custom_providers: str | None = None
```

### 6.3 Executor Selection

```python
async def execute_task(task: PendingTask, config: SidecarConfig) -> AsyncGenerator[TaskEvent, None]:
    """Select and run the appropriate executor for a task."""
    workflow_pipeline = task.input.get("_pipeline")

    if workflow_pipeline is None:
        # Legacy single-shot execution
        executor = LocalExecutor(handler_command=config.fleet_executor_command)
        async for event in executor.execute(task):
            yield event
    else:
        # Multi-step pipeline execution
        router = build_model_router(config)
        pipeline = PipelineDefinition(**workflow_pipeline)
        executor = PipelineExecutor(router=router)
        async for event in executor.execute(pipeline, task.input):
            yield event
```

---

## 7. Candidate Workflows

### 7.1 HIGH Fit (Immediate Candidates)

| Workflow | Steps | Models | Gate Types | Current Implementation |
|----------|-------|--------|------------|----------------------|
| Agent Reflections | 4 (context + 3 LLM) | Opus + Mercury-2 | threshold (output length) | `agent_reflections/cli.py` -- 3 sequential urllib calls |
| Context Gathering | 3 (scan + assemble + validate) | None (code only) | schema (required fields) | `hooks/subagent-start-load.sh` + `context_assembler.py` |
| Pre-Compact Save | 3 (parse + search + file) | None (code only) | threshold (content length) | `hooks/pre-compact-save.sh` |
| Static Analysis | 3 (pyscn + deepcsim + synthesize) | Sonnet (synthesis) | schema + threshold | Manual CLI commands |
| Vibe-Check | 2 (analyze + grade) | None (code only) | threshold (score range) | `vibe-check` CLI |
| Research Synthesis | 3 (extract + synthesize + judge) | Haiku + Sonnet + Opus | schema + threshold | Manual in Claude Code |

### 7.2 LOW Fit (Stay in Claude Code)

| Process | Why |
|---------|-----|
| Session start checklist | Tied to session lifecycle |
| Post-compact restore | Must inject into active session context |
| Memory-md guard | PreToolUse hook -- needs tool call interception |
| ACP monitor | Observes active sessions, nudges via tmux |
| Composition gap nudge | Stop hook -- needs idle detection |

### 7.3 First Implementation Target

**Agent Reflections** is the ideal first pipeline workflow because:

1. Already has a clean 3-step sequential structure (Layer 1 -> Layer 2 -> Layer 3)
2. Already uses a different model conceptually (Mercury-2 for all three layers, but the design calls for Opus on Layers 1+3)
3. Has clear gate criteria (output length, content quality)
4. Small enough to validate the architecture end-to-end
5. Dan specifically named it as a candidate

---

## 8. Cost Model

### 8.1 Per-Step Cost Tracking

Every `StepResult` includes `cost_usd`. The pipeline accumulates total cost in `PipelineState.total_cost_usd`. If `max_total_cost_usd` is set, the pipeline aborts if exceeded.

### 8.2 Cost Comparison: Current vs Pipeline

**Agent Reflections** (3 LLM calls):

| Implementation | Model | Tokens per call | Cost per run |
|----------------|-------|----------------|--------------|
| Current (all Mercury-2) | Mercury-2 x3 | ~2K in + ~1K out each | ~$0.003 x3 = ~$0.009 |
| Pipeline (Opus + Mercury + Opus) | Mixed | ~2K in + ~1K out each | ~$0.045 + $0.001 + $0.045 = ~$0.091 |
| Pipeline (Sonnet + Mercury + Sonnet) | Mixed | ~2K in + ~1K out each | ~$0.012 + $0.001 + $0.012 = ~$0.025 |

The multi-model approach costs more per run but produces higher quality on the analysis and observation layers. The workflow definition makes the tradeoff explicit and tunable per step.

### 8.3 Cost Optimization Lever

Per-workflow `max_input_tokens` on each step prevents context bloat. A 10-step pipeline where each step receives only what it needs (rather than the full conversation history) can use 5 models and never exceed 8K tokens per step. This is impossible in Claude Code, where the entire context window accumulates across turns.

---

## 9. File Layout

```
src/fleet_agent/
  executor.py              # Existing LocalExecutor (unchanged)
  pipeline/
    __init__.py             # Package exports
    executor.py             # PipelineExecutor
    models.py               # StepDefinition, GateDefinition, PipelineDefinition
    gates.py                # SchemaGate, ThresholdGate, CustomGate
    providers/
      __init__.py           # LLMProvider ABC, LLMRequest, LLMResponse
      anthropic.py          # AnthropicProvider
      inception.py          # InceptionProvider (Mercury-2)
      openai_compat.py      # OpenAICompatProvider (xAI, MiniMax, etc.)
    router.py               # ModelRouter
    context.py              # Context assembly and template rendering
    errors.py               # PipelineError
```

Each file stays under 150 lines. The provider implementations are deliberately thin -- they normalize the call interface, not replicate full SDK features.

---

## 10. Migration Path

### Phase 1: Pipeline executor core (code + tool steps only, no LLM)
- Implement `PipelineExecutor`, `StepDefinition`, gates
- Port `pre-compact-save` and `context-gathering` as code-only pipelines
- Validate the step sequencing and gate enforcement patterns

### Phase 2: Model router + LLM steps
- Implement `ModelRouter`, `AnthropicProvider`, `InceptionProvider`
- Port `agent-reflections` as the first multi-model pipeline
- Validate cost tracking and budget enforcement

### Phase 3: Fleet-API integration
- Add `pipeline` column to `Workflow` model
- Extend workflow registration API to accept step definitions
- Implement executor selection (legacy vs pipeline) in the sidecar

### Phase 4: Additional providers + workflows
- Add `OpenAICompatProvider` for xAI and MiniMax
- Port `static-analysis` and `research-synthesis` workflows
- Production hardening: retry logic, timeout handling, observability

---

## 11. Open Questions

1. **Parallel steps**: Should the pipeline support parallel step execution (e.g., pyscn and deepcsim run simultaneously)? The current design is linear. Adding a `parallel_group` field to steps would enable this but adds complexity.

2. **Streaming within steps**: Should LLM steps stream responses? The current design waits for the full response before running the gate. Streaming would improve latency feedback but complicates gate checking.

3. **Step-level tool calling**: Should LLM steps support tool calling (agentic loops within a single step)? This would turn some steps into multi-turn conversations. The current design is single-turn per LLM step. Dan's directive emphasizes deterministic control, which suggests keeping individual steps simple and using more steps rather than agentic loops within steps.

4. **Pipeline definition storage**: Should pipeline definitions live in the database (dynamic) or in code (static)? The current design puts them in the database (JSONB column). An alternative is a pipeline registry in the fleet-agent codebase, referenced by ID.

5. **Secrets management**: API keys for multiple providers need secure storage. The current design uses environment variables. A secrets manager integration may be needed for production.

---

## 12. Relationship to Existing Architecture

| Component | Role | Unchanged? |
|-----------|------|------------|
| Fleet-API server | Task dispatch, workflow registration | Extended (pipeline column) |
| Fleet Agent sidecar | Polls tasks, streams events | Extended (executor selection) |
| LocalExecutor | Single-shot subprocess execution | Unchanged (legacy fallback) |
| PipelineExecutor | Multi-step pipeline execution | **New** |
| ModelRouter | Routes model aliases to providers | **New** |
| LLMProviders | API clients for each model vendor | **New** |
| Workflow model | Workflow metadata | Extended (pipeline field) |
| Task model | Task lifecycle state machine | Unchanged |
| TaskEvent model | Event streaming | Unchanged (events are provider-agnostic) |

The existing `TaskEvent` protocol (event_type + data + sequence) works unchanged. Pipeline steps emit progress events with step metadata. The sidecar streams these to fleet-api identically to how it streams LocalExecutor events. The fleet-api server does not need to know whether a task was executed by a pipeline or a subprocess.

---

## 13. Provenance

This design synthesizes:
- Dan's directive on deterministic pipelines, multi-model routing, and per-workflow cost optimization (2026-03-17, relayed by Sage)
- Agent Reflections implementation (`finml-sage/agent-reflections`) as the canonical multi-step pipeline example
- Fleet-API RFC 0 (Principal Orchestrator Pattern), RFC 1 (Agentic Task API), RFC 2 (Pi.dev Sub-Agent Architecture)
- Existing `LocalExecutor` in `src/fleet_agent/executor.py`
- Pi.dev extension architecture analysis (nexus-marbell atlas)
- xAI bridge translation layer patterns (`vantasnerdan/claude-code-xai`)
- Mercury-2 bridge port experience (`nexus-marbell/claude-code-mercury`)

The design preserves RFC 1 and RFC 2 compatibility. Pipeline execution is a new capability layered on top of the existing architecture, not a replacement. The graduation pattern holds: Claude Code rules -> hooks -> harness. This design is the harness layer.
