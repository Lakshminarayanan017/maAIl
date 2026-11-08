"""The bounded run loop, and the trace it leaves behind.

Three caps, all enforced here rather than hoped for: steps, tokens and wall
clock. Exceeding any of them is not an exception that bubbles out; it is a
**recorded terminal state** on ``agent_runs``, because a run that vanished
is a run nobody can explain to the person whose summary never appeared.

Every step is written to ``agent_steps`` with its tokens and latency. Tool
results are stored as a digest and a byte count, never as content: a trace
holding raw email text is a second copy of the mailbox in a table nobody
guards (gap D8).

The loop holds no tools of its own. Everything reaches it through the MCP
client host, filtered by the agent's plane, which is why a Plane U agent
cannot be talked into an action by the email it just read.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.logging import bind_contextvars, get_logger
from app.modules.agents.runtime.spec import AgentSpec
from app.modules.mcp.client_manager import ClientHost
from app.modules.providers.llm.base import Completion, LLMError, LLMProvider, Prompt, price_micros

log = get_logger(__name__)

__all__ = ["RunOutcome", "RunResult", "run_agent"]

_START_RUN = text(
    """
    INSERT INTO agent_runs
        (user_id, agent_id, agent_version, plane, trigger, subject_type, subject_id,
         parent_run_id, depth, status, model, started_at)
    VALUES (:user_id, :agent_id, :agent_version, :plane, :trigger, :subject_type, :subject_id,
            :parent_run_id, :depth, 'running', :model, now())
    RETURNING id
    """
)

_FINISH_RUN = text(
    """
    UPDATE agent_runs
       SET status = :status, output = :output, error = :error,
           input_tokens = :input_tokens, output_tokens = :output_tokens,
           cached_input_tokens = :cached_input_tokens, cost_micros = :cost_micros,
           step_count = :step_count, finished_at = now()
     WHERE id = :run_id
    """
)

_ADD_STEP = text(
    """
    INSERT INTO agent_steps
        (run_id, user_id, seq, kind, tool_name, tool_args,
         tool_result_digest, tool_result_bytes, input_tokens, output_tokens, latency_ms)
    VALUES (:run_id, :user_id, :seq, :kind, :tool_name, :tool_args,
            :digest, :bytes, :input_tokens, :output_tokens, :latency_ms)
    """
)

#: How deep a run may spawn before it is treated as a cycle (gap C3).
MAX_DEPTH = 3


class RunOutcome(str, Enum):
    succeeded = "succeeded"
    failed = "failed"
    cap_exceeded = "cap_exceeded"


@dataclass
class RunResult:
    run_id: UUID
    outcome: RunOutcome
    output: dict[str, Any] | None = None
    error: str | None = None
    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_micros: int = 0
    stopped_because: str = ""
    tool_calls: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.outcome is RunOutcome.succeeded


async def run_agent(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    user_prompt: str,
    trigger: str,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    depth: int = 0,
) -> RunResult:
    """Run one agent to completion, a cap, or a failure. Always traced."""
    if depth > MAX_DEPTH:
        raise ValueError(f"{spec.id}: refusing to run at depth {depth}")

    run_id = UUID(
        str(
            (
                await session.execute(
                    _START_RUN,
                    {
                        "user_id": str(user_id),
                        "agent_id": spec.id,
                        "agent_version": spec.version,
                        "plane": spec.plane.value,
                        "trigger": trigger,
                        "subject_type": subject_type,
                        "subject_id": str(subject_id) if subject_id else None,
                        "parent_run_id": str(parent_run_id) if parent_run_id else None,
                        "depth": depth,
                        "model": provider.model_id,
                    },
                )
            ).scalar_one()
        )
    )
    bind_contextvars(run_id=str(run_id), agent=spec.id)

    # The tools this agent is told exist. Plane first, then its own
    # allowlist; nothing outside the intersection is ever mentioned.
    tools = host.tools_for(agent_plane=spec.plane, allowlist=spec.tools or None)
    tool_schemas = [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]

    result = RunResult(run_id=run_id, outcome=RunOutcome.failed)
    clock = get_clock()
    started = clock.monotonic()
    seq = 0
    conversation = user_prompt

    try:
        while True:
            if seq >= spec.budgets.max_steps:
                result.outcome = RunOutcome.cap_exceeded
                result.stopped_because = f"max_steps ({spec.budgets.max_steps})"
                break
            elapsed = clock.monotonic() - started
            if elapsed > spec.budgets.max_wall_clock_s:
                result.outcome = RunOutcome.cap_exceeded
                result.stopped_because = f"max_wall_clock_s ({spec.budgets.max_wall_clock_s})"
                break
            if result.input_tokens + result.output_tokens > spec.budgets.max_tokens:
                result.outcome = RunOutcome.cap_exceeded
                result.stopped_because = f"max_tokens ({spec.budgets.max_tokens})"
                break

            seq += 1
            call_started = time.perf_counter()
            completion = await _complete(
                provider,
                Prompt(
                    system=spec.system_prompt,
                    user=conversation,
                    output_schema=spec.output_schema,
                    tools=tool_schemas,
                    max_output_tokens=min(1024, spec.budgets.max_tokens),
                ),
            )
            latency_ms = int((time.perf_counter() - call_started) * 1000)

            result.input_tokens += completion.input_tokens
            result.output_tokens += completion.output_tokens
            result.cached_input_tokens += completion.cached_input_tokens
            result.cost_micros += price_micros(
                completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )

            await session.execute(
                _ADD_STEP,
                {
                    "run_id": str(run_id),
                    "user_id": str(user_id),
                    "seq": seq,
                    "kind": "llm",
                    "tool_name": None,
                    "tool_args": None,
                    "digest": None,
                    "bytes": None,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "latency_ms": latency_ms,
                },
            )

            if not completion.wants_tools:
                result.output = _parse_output(completion, spec)
                result.outcome = (
                    RunOutcome.succeeded if result.output is not None else RunOutcome.failed
                )
                if result.output is None:
                    result.error = "output did not satisfy the declared schema"
                break

            for call in completion.tool_calls:
                seq += 1
                result.tool_calls.append(call.name)
                tool_result = await host.invoke(
                    call.name,
                    call.arguments,
                    agent_plane=spec.plane,
                    allowlist=spec.tools or None,
                )
                await session.execute(
                    _ADD_STEP,
                    {
                        "run_id": str(run_id),
                        "user_id": str(user_id),
                        "seq": seq,
                        "kind": "tool",
                        "tool_name": call.name,
                        "tool_args": json.dumps(call.arguments, default=str),
                        # A digest, never the content.
                        "digest": tool_result.digest,
                        "bytes": tool_result.byte_size,
                        "input_tokens": None,
                        "output_tokens": None,
                        "latency_ms": tool_result.latency_ms,
                    },
                )
                conversation += (
                    f"\n\n[tool {call.name} returned "
                    f"{json.dumps(tool_result.value, default=str)[:2000]}]"
                )

    except PermissionError as exc:
        result.outcome = RunOutcome.failed
        result.error = str(exc)
        log.warning("agent.tool_refused", agent=spec.id, error=str(exc))
    except LLMError as exc:
        result.outcome = RunOutcome.failed
        result.error = str(exc)
    except Exception as exc:
        result.outcome = RunOutcome.failed
        result.error = f"{type(exc).__name__}: {exc}"
        log.exception("agent.crashed", agent=spec.id)

    result.steps = seq
    await session.execute(
        _FINISH_RUN,
        {
            "run_id": str(run_id),
            "status": result.outcome.value,
            "output": json.dumps(result.output) if result.output is not None else None,
            "error": json.dumps(
                {"message": result.error, "stopped_because": result.stopped_because}
            )
            if (result.error or result.stopped_because)
            else None,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cached_input_tokens": result.cached_input_tokens,
            "cost_micros": result.cost_micros,
            "step_count": min(seq, 32767),
        },
    )

    log.info(
        "agent.finished",
        agent=spec.id,
        outcome=result.outcome.value,
        steps=result.steps,
        cost_micros=result.cost_micros,
        stopped_because=result.stopped_because or None,
    )
    return result


async def _complete(provider: LLMProvider, prompt: Prompt) -> Completion:
    try:
        return await provider.complete(prompt)
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc


def _parse_output(completion: Completion, spec: AgentSpec) -> dict[str, Any] | None:
    """Validate against the declared schema. None means it did not satisfy it.

    Deliberately strict about the required keys and nothing more: a full
    JSON Schema validator is a dependency, and the properties that matter
    are the ones the caller is about to read.
    """
    try:
        parsed = json.loads(completion.text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    for name in spec.output_schema.get("required", []):
        if name not in parsed:
            return None
    return parsed
