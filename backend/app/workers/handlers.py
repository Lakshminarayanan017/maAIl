"""Job handlers. Importing this module is what registers them.

Kept apart from the loop so the worker's control flow and the work itself
fail independently, and so a handler can be read without the scheduling
around it.
"""

from __future__ import annotations

from uuid import UUID

from app.core.logging import get_logger
from app.core.tenancy import tenant_session
from app.jobs import queue
from app.modules.agents.defs import triage as triage_service
from app.modules.mcp import bootstrap
from app.modules.providers.llm.base import ModelTier
from app.modules.providers.llm.stub import StubProvider
from app.workers.runner import register

log = get_logger(__name__)


@register("agent.triage")
async def handle_triage(job: queue.Job) -> None:
    """Classify one thread.

    The dedupe key is ``triage:{thread_id}`` with a debounce, so a burst
    of five messages on one thread arrives here once (gap C5).
    """
    if job.user_id is None:
        log.warning("triage.job_without_user", job_id=job.id)
        return

    thread_id = job.payload.get("thread_id")
    if not thread_id:
        log.warning("triage.job_without_thread", job_id=job.id)
        return

    runtime = bootstrap.runtime()
    spec = runtime.agents.get(triage_service.AGENT_ID)
    if spec is None:
        raise RuntimeError("the triage agent is not loaded")

    async with tenant_session(job.user_id) as session:
        outcome = await triage_service.triage_thread(
            session,
            spec=spec,
            provider=StubProvider(tier=ModelTier.small),
            host=runtime.host,
            user_id=job.user_id,
            thread_id=UUID(str(thread_id)),
        )

    if outcome is not None:
        log.info(
            "triage.done",
            thread_id=str(thread_id),
            category=outcome.category,
            priority=outcome.priority,
            source=outcome.source,
        )
