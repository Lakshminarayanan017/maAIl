"""Agent runs and their traces.

The trace is the product feature nobody asks for and everybody needs the
first time an agent says something wrong. Without a per-step record of what
was called, with what, and what it cost, an agent bug is unreproducible and
an expensive agent is unidentifiable (gaps C1, B4).

Tool results appear as a digest and a byte count, never as content. A trace
view that printed tool output would be a second way to read the mailbox,
in a screen nobody thinks of as holding mail (gap D8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.modules.agents.runtime import run_agent
from app.modules.harness import budget as budget_manager
from app.modules.harness.context_builder import build_thread_context
from app.modules.mcp import bootstrap
from app.modules.providers.llm.base import ModelTier
from app.modules.providers.llm.stub import StubProvider

router = APIRouter(tags=["runs"])
log = get_logger(__name__)


class StepOut(BaseModel):
    seq: int
    kind: str
    tool_name: str | None
    tool_args: dict[str, Any] | None
    #: A hash of what the tool returned. Never the content.
    tool_result_digest: str | None
    tool_result_bytes: int | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    created_at: datetime


class RunOut(BaseModel):
    id: UUID
    agent_id: str
    agent_version: str
    plane: str
    trigger: str
    subject_type: str | None
    subject_id: UUID | None
    status: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_micros: int
    step_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class RunDetail(RunOut):
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    steps: list[StepOut]


class BudgetOut(BaseModel):
    state: str
    spent_micros: int
    soft_cap_micros: int
    hard_cap_micros: int
    remaining_micros: int


class HelloRequest(BaseModel):
    thread_id: UUID


_LIST = text(
    """
    SELECT id, agent_id, agent_version, plane, trigger, subject_type, subject_id,
           status::text, model, input_tokens, output_tokens, cached_input_tokens,
           cost_micros, step_count, started_at, finished_at, created_at
      FROM agent_runs
     ORDER BY created_at DESC
     LIMIT :limit
    """
)

_ONE = text(
    """
    SELECT id, agent_id, agent_version, plane, trigger, subject_type, subject_id,
           status::text, model, input_tokens, output_tokens, cached_input_tokens,
           cost_micros, step_count, started_at, finished_at, created_at, output, error
      FROM agent_runs WHERE id = :run_id
    """
)

_STEPS = text(
    """
    SELECT seq, kind, tool_name, tool_args, tool_result_digest, tool_result_bytes,
           input_tokens, output_tokens, latency_ms, created_at
      FROM agent_steps WHERE run_id = :run_id ORDER BY seq
    """
)


def _to_run(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "agent_id": row[1],
        "agent_version": row[2],
        "plane": row[3],
        "trigger": row[4],
        "subject_type": row[5],
        "subject_id": row[6],
        "status": row[7],
        "model": row[8],
        "input_tokens": row[9],
        "output_tokens": row[10],
        "cached_input_tokens": row[11],
        "cost_micros": row[12],
        "step_count": row[13],
        "started_at": row[14],
        "finished_at": row[15],
        "created_at": row[16],
    }


@router.get("/runs", response_model=list[RunOut], summary="Recent agent runs")
async def list_runs(
    auth: AuthContext, limit: Annotated[int, Query(ge=1, le=100)] = 25
) -> list[RunOut]:
    # RLS scopes this; there is no user_id clause to forget.
    rows = (await auth.session.execute(_LIST, {"limit": limit})).all()
    return [RunOut(**_to_run(row)) for row in rows]


@router.get("/runs/{run_id}", response_model=RunDetail, summary="One run and its steps")
async def read_run(run_id: UUID, auth: AuthContext) -> RunDetail:
    row = (await auth.session.execute(_ONE, {"run_id": str(run_id)})).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such run")

    steps = (await auth.session.execute(_STEPS, {"run_id": str(run_id)})).all()
    return RunDetail(
        **_to_run(row),
        output=row[17],
        error=row[18],
        steps=[
            StepOut(
                seq=step[0],
                kind=step[1],
                tool_name=step[2],
                tool_args=step[3],
                tool_result_digest=step[4],
                tool_result_bytes=step[5],
                input_tokens=step[6],
                output_tokens=step[7],
                latency_ms=step[8],
                created_at=step[9],
            )
            for step in steps
        ],
    )


@router.get("/runs-budget", response_model=BudgetOut, summary="This month's spend")
async def read_budget(auth: AuthContext) -> BudgetOut:
    standing = await budget_manager.check(auth.session, auth.user_id)
    return BudgetOut(
        state=standing.state.value,
        spent_micros=standing.spent_micros,
        soft_cap_micros=standing.soft_cap_micros,
        hard_cap_micros=standing.hard_cap_micros,
        remaining_micros=standing.remaining_micros,
    )


@router.post(
    "/runs/hello",
    response_model=RunDetail,
    dependencies=[Depends(require_csrf)],
    summary="Run the hello agent against a thread, for the trace",
)
async def run_hello(body: HelloRequest, auth: AuthContext) -> RunDetail:
    """The phase 5 demo: one run, inspectable end to end, with its cost.

    Synchronous on purpose. This is the route that proves the runtime
    works; queueing it would prove the queue works, which phase 4 already
    did, and would make the demo two screens instead of one.
    """
    runtime = bootstrap.runtime()
    spec = runtime.agents.get("hello")
    if spec is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The hello agent is not loaded")

    context = await build_thread_context(
        auth.session,
        thread_id=body.thread_id,
        system=spec.system_prompt,
        question=(
            f"user_id: {auth.user_id}\nthread_id: {body.thread_id}\n"
            "Call mail.get_thread with those values, then answer."
        ),
        max_tokens=spec.budgets.max_tokens // 2,
    )

    result = await run_agent(
        auth.session,
        spec=spec,
        provider=StubProvider(tier=ModelTier.small),
        host=runtime.host,
        user_id=auth.user_id,
        user_prompt=context.render(),
        trigger="user_requested",
        subject_type="thread",
        subject_id=body.thread_id,
    )

    await budget_manager.spend(auth.session, auth.user_id, result.cost_micros)
    return await read_run(result.run_id, auth)
