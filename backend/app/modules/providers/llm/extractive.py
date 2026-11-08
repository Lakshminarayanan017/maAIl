"""Deterministic extraction, used where a model would otherwise be.

This is what the stub provider answers with, and it is worth being exact
about what it is and is not.

It is **extraction**: it finds sentences that are already in the email and
hands them back with their real character offsets. Every span it produces
resolves, because it produced the span by slicing the text it was given.

It is **not intelligence**. It cannot tell a marketing "URGENT" from a
supervisor's quiet sentence, and it does not try. The summary it returns
is the thread's own opening sentences, which a reader will recognise
immediately as not a summary.

Why bother, rather than returning ``"stub:a1b2c3"``:

**The evidence path only exists if something exercises it.** Phase 8's
gate is that every AI value resolves to a real span. A stub returning a
digest string produces zero spans, so every value renders "not
determined", so the gate passes while testing nothing. Extraction
produces real spans that really resolve, and the gate then means
something.

**It is the deterministic alternative, written down and run.** Every
manifest has to state why code cannot do its job. For the action-items
agent the honest answer includes "imperative detection finds a usable
share of stated requests, and here is how far that gets you" -- so here
it is, actually running, which makes the claim checkable rather than
rhetorical.

The output is marked as coming from the ``stub`` model everywhere it is
stored, and the provider refuses to exist in production.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["MessageBlock", "answer", "parse_blocks"]


@dataclass(frozen=True)
class MessageBlock:
    """One message as the context builder rendered it."""

    message_id: str
    sender: str
    body: str


#: Matches the format ``harness/context_builder._block`` writes. The two
#: are coupled on purpose and a test asserts they stay in step: an
#: extractor reading a format nobody writes any more would silently return
#: nothing, which looks exactly like an email with nothing in it.
_BLOCK = re.compile(
    r"Message:\s*(?P<id>[0-9a-fA-F-]{36})\s*\n"
    r"From:\s*(?P<from>.*?)\n"
    r"Date:\s*.*?\n"
    r"Body \(character offsets below start at 0\):\n"
    r"(?P<body>.*?)"
    # Stops at the next block, at the end of the delimited thread, or at
    # the end of the text -- in that order. Without the closing tags the
    # last body swallows whatever follows it, and the prompt's own
    # question turns up as one of the email's action items. It did.
    r"(?=\n\n---\n\n|\n</thread>|\n</retrieved_mail>|\Z)",
    re.DOTALL,
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

#: Phrasings that ask for something. Deliberately a short list: this is
#: the weak deterministic baseline the agents' manifests describe, not an
#: attempt to be good at the job.
_REQUEST = re.compile(
    r"\b(please|could you|can you|would you|kindly|let me know|"
    r"we need|you need to|make sure|don't forget|remember to|"
    r"send (?:me|us|over)|confirm|review|approve|sign|submit|respond)\b",
    re.I,
)

_TECHNOLOGIES = (
    "postgres",
    "postgresql",
    "python",
    "typescript",
    "javascript",
    "react",
    "docker",
    "kubernetes",
    "redis",
    "spring boot",
    "java",
    "rust",
    "go",
    "fastapi",
    "django",
    "node",
    "graphql",
    "terraform",
)

#: ``owner/name`` as it appears in build output and review mail.
_REPO = re.compile(r"\b([a-z0-9][\w.-]{1,38}/[a-z0-9][\w.-]{1,38})\b", re.I)
#: A line that looks like a failure rather than prose.
_ERROR = re.compile(
    r"^[^\n]*\b(error|exception|failed|failure|traceback|assertionerror|"
    r"timeout|refused|fatal)\b[^\n]*$",
    re.I | re.M,
)


def parse_blocks(prompt: str) -> list[MessageBlock]:
    """Pull the message blocks back out of a rendered prompt."""
    return [
        MessageBlock(
            message_id=match.group("id"),
            sender=match.group("from").strip(),
            body=match.group("body"),
        )
        for match in _BLOCK.finditer(prompt)
    ]


def _sentences(body: str) -> list[tuple[int, int, str]]:
    """Sentences with their real offsets into ``body``.

    Offsets are tracked by walking the original string rather than by
    re-finding each sentence, so a sentence that appears twice does not
    collapse onto the first occurrence's span.
    """
    out: list[tuple[int, int, str]] = []
    cursor = 0
    for piece in _SENTENCE_END.split(body):
        if not piece:
            continue
        start = body.find(piece, cursor)
        if start < 0:
            continue
        end = start + len(piece)
        cursor = end
        text = piece.strip()
        if len(text) >= 12:
            out.append((start, end, text))
    return out


def _schema_fields(schema: dict[str, Any]) -> frozenset[str]:
    properties = schema.get("properties") or {}
    return frozenset(str(key) for key in properties)


# ---------------------------------------------------------------------------
# One answerer per agent shape. Dispatch is on the schema's own fields, so
# an agent whose schema changes stops matching rather than quietly getting
# an answer shaped for a different agent.
# ---------------------------------------------------------------------------
def _summarizer(blocks: list[MessageBlock], prompt: str) -> dict[str, Any]:
    if not blocks:
        return {
            "summary": "",
            "bullet_points": [],
            "evidence": [],
            "intent": "other",
            "intent_reason": "",
            "intent_confidence": "low",
            "entities": [],
        }

    # The newest message, because that is what the thread is currently
    # about. The opening message is history.
    newest = blocks[-1]
    sentences = _sentences(newest.body)
    lead = sentences[:2]

    summary = " ".join(text for _, _, text in lead)
    evidence = [
        {"message_id": newest.message_id, "char_start": start, "char_end": end}
        for start, end, _ in lead
    ]

    asked = next((s for s in sentences if _REQUEST.search(s[2])), None)
    if asked is not None:
        intent = "reply_requested" if "?" in asked[2] else "action_requested"
        reason = f"The sender wrote: {asked[2][:120]}"
    elif any("?" in text for _, _, text in sentences):
        intent, reason = "reply_requested", "The message contains a direct question."
    else:
        intent, reason = "information_only", "Nothing in the message asks for anything."

    entities: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, value: str, start: int, end: int) -> None:
        key = f"{kind}:{value.lower()}"
        if key in seen or len(entities) >= 20:
            return
        seen.add(key)
        entities.append(
            {
                "kind": kind,
                "value": value,
                # Everything here was literally in the text. Nothing this
                # extractor produces is ever 'interpreted', because it
                # interprets nothing.
                "provenance": "stated",
                "message_id": newest.message_id,
                "char_start": start,
                "char_end": end,
            }
        )

    for match in _REPO.finditer(newest.body):
        add("repository", match.group(1), match.start(1), match.end(1))
    for technology in _TECHNOLOGIES:
        # Word boundaries, not substrings. A plain `find` matched "go"
        # inside "got 503" and put Go on screen as a technology this
        # email names. Seen on a real thread, which is why short entries
        # like "go" and "node" are in the list at all -- they are the
        # ones that make this mistake visible.
        found = re.search(rf"\b{re.escape(technology)}\b", newest.body, re.I)
        if found:
            add("technology", found.group(0), found.start(), found.end())
    for match in _ERROR.finditer(newest.body):
        line = match.group(0).strip()
        if line:
            add("error_message", line[:200], match.start(), match.end())
    if newest.sender:
        organization = newest.sender.split("@")[-1].strip(">")
        at = newest.body.find(organization)
        if at >= 0:
            add("organization", organization, at, at + len(organization))

    return {
        "summary": summary,
        "bullet_points": [text for _, _, text in sentences[2:5]],
        "evidence": evidence,
        "intent": intent,
        "intent_reason": reason[:200],
        # Never 'high'. Extraction has no business being confident about
        # what a sender wants.
        "intent_confidence": "low",
        "entities": entities,
    }


#: The candidate list the deadline service renders into its question. The
#: format lives here and there; a test keeps them in step.
_CANDIDATE = re.compile(
    r"^\s*\[(?P<index>\d+)\]\s+\"(?P<phrase>[^\"]*)\"\s+"
    r"kind=(?P<kind>\S+)\s+resolved=(?P<resolved>\S+)\s+confidence=(?P<band>\S+)",
    re.M,
)


def _around(body: str, phrase: str, window: int = 220) -> str:
    """The sentence or so surrounding a phrase, or empty if it is absent."""
    at = body.lower().find(phrase.lower())
    if at < 0:
        return ""
    return body[max(0, at - window) : at + len(phrase) + window]


def _deadline(blocks: list[MessageBlock], prompt: str) -> dict[str, Any]:
    """Classify the candidates the parser found. No dates are produced.

    The extractor has the same constraint the model does: there is no date
    field in the schema, so the only thing it can do is label candidates.
    """
    deadlines = []
    for match in _CANDIDATE.finditer(prompt):
        index = int(match.group("index"))
        kind = match.group("kind")
        resolved = match.group("resolved") != "none"
        phrase = match.group("phrase")

        # A date near request language is a candidate for being a
        # commitment. This is the weak baseline, and it is wrong on "we
        # shipped the fix on Friday" in exactly the way the manifest says.
        #
        # The context has to come from the **message body**, not from the
        # candidate list: the list is rendered in the question, where the
        # neighbouring text is other candidates and an instruction, so
        # looking there finds no request language in any thread and
        # classifies every deadline away. Found by running it.
        looks_asked = bool(_REQUEST.search(phrase)) or any(
            _REQUEST.search(_around(block.body, phrase)) for block in blocks
        )

        deadlines.append(
            {
                "candidate_index": index,
                "is_deadline": resolved and looks_asked,
                "date_type": kind,
                "resolution_status": "resolved" if resolved else "unresolved",
                "confidence_band": "low",
                "is_for_user": looks_asked,
                "reason": (
                    "The phrase sits next to request language."
                    if looks_asked
                    else "Nothing nearby asks the reader for anything."
                ),
            }
        )
    return {"deadlines": deadlines}


def _action_items(blocks: list[MessageBlock], prompt: str) -> dict[str, Any]:
    """Imperative and question detection, and nothing else.

    Everything it finds is ``stated`` with a real span, because it cannot
    infer. An extractor that emitted ``inferred`` items would be inventing
    them, which is the failure mode the two labels exist to prevent.
    """
    items: list[dict[str, Any]] = []
    for block in blocks:
        for start, end, text in _sentences(block.body):
            if len(items) >= 10:
                break
            if not (_REQUEST.search(text) or text.rstrip().endswith("?")):
                continue
            items.append(
                {
                    "description": text[:300],
                    # Who it belongs to needs the sentence's meaning, which
                    # is the judgement this baseline does not have.
                    "owner": "unclear",
                    "source": "stated",
                    "message_id": block.message_id,
                    "char_start": start,
                    "char_end": end,
                }
            )
    return {"items": items, "follow_up_needed": bool(items)}


def _companion(blocks: list[MessageBlock], prompt: str) -> dict[str, Any]:
    """Quote what was retrieved. Do not characterise it.

    The one thing a question-answering extractor must not do is paraphrase,
    because a paraphrase is a claim and this has no way to check one. So it
    says where it looked and quotes, with the span.
    """
    if not blocks:
        return {
            "answer": ("I could not find anything in your mail to answer that from."),
            "citations": [],
            "follow_ups": [],
        }

    citations = []
    quoted = []
    for block in blocks[:3]:
        sentences = _sentences(block.body)
        if not sentences:
            continue
        start, end, text = sentences[0]
        citations.append({"message_id": block.message_id, "char_start": start, "char_end": end})
        quoted.append(f"— {block.sender}: “{text[:200]}”")

    return {
        "answer": (
            f"{len(blocks)} message{'s' if len(blocks) != 1 else ''} match. " + "\n".join(quoted)
        ),
        "citations": citations,
        "follow_ups": [],
    }


def _hello(blocks: list[MessageBlock], prompt: str) -> dict[str, Any]:
    return {"greeting": "hello", "thread_subject": ""}


#: Required-field signatures, most specific first. Matching on the fields
#: an agent declares rather than on its id keeps this provider from
#: needing to know which agents exist.
_ANSWERERS = (
    (frozenset({"summary", "intent", "entities"}), _summarizer),
    (frozenset({"deadlines"}), _deadline),
    (frozenset({"items", "follow_up_needed"}), _action_items),
    (frozenset({"answer", "citations"}), _companion),
)


def answer(prompt: str, schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extractive output for a known schema, or None.

    None is the honest answer for a schema this does not recognise: the
    caller then falls back to filling required fields with something
    visibly synthetic, rather than this guessing at a shape it has never
    seen.
    """
    if not schema:
        return None

    fields = _schema_fields(schema)
    blocks = parse_blocks(prompt)

    for signature, answerer in _ANSWERERS:
        if signature <= fields:
            return answerer(blocks, prompt)
    return None
