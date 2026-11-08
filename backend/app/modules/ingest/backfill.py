"""Fill ``body_text_stripped`` for messages ingested before the stripper.

Phase 2 stored bodies; phase 3 added the stripper. Rows written in between
have a body and no stripped text, and every agent reads the stripped
column — so without this they would be invisible to the whole intelligence
layer, which is a worse failure than being merely unstripped.

Runs in batches with its own transaction each, so it can be interrupted and
restarted. Deterministic and free: no model, no network.

    python -m app.modules.ingest.backfill
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.database.models.thread import EmailMessage
from app.modules.ingest.quote_stripper import strip_quotes

log = get_logger(__name__)

BATCH = 500


@dataclass
class BackfillSummary:
    scanned: int = 0
    updated: int = 0
    total_before: int = 0
    total_after: int = 0

    @property
    def saved_ratio(self) -> float:
        if self.total_before == 0:
            return 0.0
        return round(1 - (self.total_after / self.total_before), 4)


async def backfill() -> BackfillSummary:
    engine = create_async_engine(settings.owner_database_url, echo=False)
    summary = BackfillSummary()
    try:
        while True:
            async with engine.begin() as conn:
                rows = (
                    await conn.execute(
                        select(EmailMessage.id, EmailMessage.body_text)
                        .where(
                            EmailMessage.body_text.is_not(None),
                            EmailMessage.body_text_stripped.is_(None),
                            EmailMessage.deleted_at.is_(None),
                        )
                        .limit(BATCH)
                    )
                ).all()

                if not rows:
                    break

                for message_id, body in rows:
                    result = strip_quotes(body)
                    summary.scanned += 1
                    summary.total_before += len(body or "")
                    summary.total_after += len(result.text)
                    await conn.execute(
                        update(EmailMessage)
                        .where(EmailMessage.id == message_id)
                        .values(
                            body_text_stripped=result.text,
                            stripped_ratio=result.ratio,
                        )
                    )
                    summary.updated += 1

                # Search relevance is built from the stripped text, so the
                # vectors have to move with it.
                await conn.execute(
                    text(
                        """
                        SELECT refresh_thread_tsv(t.id)
                        FROM email_threads t
                        WHERE t.id IN (
                          SELECT DISTINCT m.thread_id FROM email_messages m
                          WHERE m.id = ANY(:ids)
                        )
                        """
                    ),
                    {"ids": [row[0] for row in rows]},
                )

            log.info("backfill.batch", scanned=summary.scanned, updated=summary.updated)
    finally:
        await engine.dispose()

    return summary


async def measure() -> tuple[int, float]:
    """How many messages are stripped, and the mean saving."""
    engine = create_async_engine(settings.owner_database_url, echo=False)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(
                        func.count(EmailMessage.id),
                        func.avg(EmailMessage.stripped_ratio),
                    ).where(EmailMessage.body_text_stripped.is_not(None))
                )
            ).one()
    finally:
        await engine.dispose()
    return int(row[0] or 0), float(row[1] or 0.0)


def main() -> None:
    import sys

    configure_logging()
    summary = asyncio.run(backfill())
    counted, mean = asyncio.run(measure())
    sys.stdout.write(
        f"backfilled {summary.updated} of {summary.scanned} messages\n"
        f"this run removed {summary.saved_ratio:.1%} of their text\n"
        f"{counted} messages stripped overall, mean saving {mean:.1%}\n"
    )


if __name__ == "__main__":
    main()
