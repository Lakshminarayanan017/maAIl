"""The deterministic Triage bypass, and the asymmetry that makes it safe.

A bypass skips the model for a thread whose answer is obvious. It is the
cheapest thing in the cost model and the most dangerous, because a bypass
that is wrong does not produce a bad answer — it produces no answer, and a
thread the user never sees.

So it is **asymmetric by construction**, and all four rules below are
enforced here rather than remembered:

1. It may only **reduce work**, never change what the user sees. A bypassed
   thread still appears in the inbox, still has a category, still has a
   priority. It is just not reasoned about.
2. It requires **positive evidence of unimportance**. "Nothing matched" is
   not evidence. Every return below names something that was found.
3. It **never applies to an unknown sender**. An unfamiliar address is
   exactly the case where the cheap signal is least reliable.
4. It **never applies to something the user asked for**. They can see that
   they asked.

Bypass rate is measured and reported. It is never a target: a bypass rate
someone is trying to raise is a bypass rate that will start hiding mail.

See docs/architecture/07-harness.md §3.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.threads.significance import is_automation

__all__ = ["BypassResult", "evaluate_bypass"]

#: Gmail labels that are the provider's own judgement, already made.
_PROMOTIONAL_LABELS = frozenset({"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"})

#: Subject markers that are structurally, not semantically, bulk mail.
_BULK_MARKERS = ("unsubscribe", "view this email in your browser", "manage preferences")


@dataclass(frozen=True)
class BypassResult:
    """What the bypass decided, and the evidence for it."""

    bypassed: bool
    reason: str = ""
    category: str | None = None
    priority: int | None = None

    @property
    def explanation(self) -> str:
        """Shown to the user in place of a model's priority_reason."""
        return {
            "gmail_promotions": "Gmail filed this under Promotions",
            "bulk_unsubscribe": "Bulk mail with an unsubscribe footer",
            "automated_never_replied": "Automated sender you have never replied to",
        }.get(self.reason, self.reason)


def evaluate_bypass(
    *,
    sender: str | None,
    provider_labels: tuple[str, ...],
    body_text: str | None,
    sender_known: bool,
    sender_reply_count: int,
    user_initiated: bool = False,
) -> BypassResult:
    """Decide whether this thread can skip the model.

    Returns a category and priority when it bypasses, because rule 1 says
    the thread must still appear with a classification. A bypass that left
    the thread blank would be hiding it by another name.
    """
    if user_initiated:
        # Rule 4. They asked; they get the real thing.
        return BypassResult(False, "user_initiated")

    if not sender_known:
        # Rule 3. The cheap signals are least reliable exactly here, and
        # a first message from a new person is the one that matters most.
        return BypassResult(False, "unknown_sender")

    labels = set(provider_labels)

    if labels & _PROMOTIONAL_LABELS:
        # Positive evidence: Gmail already made this call, with signals
        # Maail does not have.
        return BypassResult(True, "gmail_promotions", category="promotional", priority=0)

    lowered = (body_text or "").lower()
    if any(marker in lowered for marker in _BULK_MARKERS):
        return BypassResult(True, "bulk_unsubscribe", category="promotional", priority=0)

    if is_automation(sender) and sender_reply_count == 0:
        # Positive evidence twice over: the address is structurally a
        # machine, and the user has never once replied to it.
        return BypassResult(True, "automated_never_replied", category="notification", priority=0)

    return BypassResult(False, "no_bypass_evidence")
