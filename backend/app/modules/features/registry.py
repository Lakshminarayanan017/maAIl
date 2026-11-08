"""The seventeen toggles, their defaults, dependencies and presets.

The list is locked (08-ui-spec.md §10) and it lives in Git rather than in
a table, for the same reason agent manifests do: a default that lives in
the database cannot be changed for existing users without a migration,
and a label that lives in the database cannot be reviewed in a diff.
``user_features`` holds only what a person has actually touched.

Two things here are not in the spec's table and are worth stating.

**Some toggles share an agent.** Priority detection and Smart
categorization are both Triage. Turning one off does not stop the agent
if the other is on; it stops that half of the result being written. A
toggle is a promise about what Maail does *to your mail*, not about which
process runs, and modelling it as one-agent-per-toggle would have forced
a second model call to honour a setting.

**Conversation tracking does not switch off thread reconstruction.**
Assembling messages into threads is Tier 0, zero-LLM, and the thing every
other feature is defined over -- an app that stopped doing it would not
work at all. What this toggle controls is the intelligence built *on* that
context: the related-context section of the detail panel. The
architecture and the UI spec disagree here if read literally, and this is
the reading that keeps both true. See AGENTS.md, zero-LLM zones.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

__all__ = [
    "ALWAYS_ON",
    "FEATURES",
    "GROUPS",
    "PRESETS",
    "Feature",
    "FeatureGroup",
    "Preset",
    "UnknownFeature",
    "default_enabled",
    "get",
    "resolve_disable",
    "resolve_enable",
    "validate_config",
]


class UnknownFeature(KeyError):
    """An id no feature claims.

    Raised rather than defaulted, because a silent default is how a
    capability ends up ungated: a typo in a FEATURE_ID would otherwise
    read as "enabled" forever.
    """


class FeatureGroup(str, Enum):
    email = "email_intelligence"
    developer = "developer_intelligence"
    productivity = "productivity"
    writing = "writing_communication"


GROUPS: dict[FeatureGroup, str] = {
    FeatureGroup.email: "Email intelligence",
    FeatureGroup.developer: "Developer intelligence",
    FeatureGroup.productivity: "Productivity",
    FeatureGroup.writing: "Writing & communication",
}


@dataclass(frozen=True)
class ConfigField:
    """One setting inside a feature's drawer."""

    key: str
    label: str
    kind: str  # "choice" | "number" | "tags"
    default: Any
    #: For "choice": the options, each with the exact wording the spec
    #: gives. Wording is part of the contract here -- "Balanced" without
    #: "important and time-sensitive emails" is a different promise.
    options: tuple[tuple[str, str, str], ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""


@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    description: str
    group: FeatureGroup
    default: bool
    #: Features this one cannot work without. Enabling pulls them in;
    #: disabling one of them pushes this off.
    requires: tuple[str, ...] = ()
    config: tuple[ConfigField, ...] = ()
    #: What the phase plan would call the arrival date. Shown as "coming
    #: in phase N" rather than as a toggle that silently does nothing.
    live: bool = True
    arrives_in_phase: int | None = None

    def default_config(self) -> dict[str, Any]:
        return {field.key: field.default for field in self.config}


# ---------------------------------------------------------------------------
# The locked list. Order within each group is the spec's order, because it
# is also the order the screen renders.
# ---------------------------------------------------------------------------
_PRIORITY_SENSITIVITY = ConfigField(
    key="sensitivity",
    label="Urgency sensitivity",
    kind="choice",
    default="balanced",
    # Verbatim from 08-ui-spec.md §10.
    options=(
        ("strict", "Strict", "only genuinely urgent emails"),
        ("balanced", "Balanced", "important and time-sensitive emails"),
        ("sensitive", "Sensitive", "include potentially important emails"),
    ),
)

FEATURES: tuple[Feature, ...] = (
    # --- Email intelligence -------------------------------------------
    Feature(
        id="priority_detection",
        name="Priority detection",
        description="Identify urgent, important and time-sensitive emails.",
        group=FeatureGroup.email,
        default=True,
        config=(_PRIORITY_SENSITIVITY,),
    ),
    Feature(
        id="smart_categorization",
        name="Smart categorization",
        description="Automatically classify emails into meaningful categories.",
        group=FeatureGroup.email,
        default=True,
        config=(
            ConfigField(
                key="custom_categories",
                label="Custom categories",
                kind="tags",
                default=[],
                help="Added alongside the eight Maail already uses.",
            ),
        ),
    ),
    Feature(
        id="instant_summaries",
        name="Instant summaries",
        description="Generate concise summaries of lengthy emails.",
        group=FeatureGroup.email,
        default=True,
        config=(
            ConfigField(
                key="length",
                label="Summary length",
                kind="choice",
                default="short",
                options=(
                    ("short", "Short", "two or three sentences"),
                    ("detailed", "Detailed", "a paragraph with the specifics"),
                ),
            ),
        ),
    ),
    Feature(
        id="action_extraction",
        name="Action extraction",
        description="Find tasks, commitments and requested actions in conversations.",
        group=FeatureGroup.email,
        default=True,
    ),
    Feature(
        id="conversation_tracking",
        name="Conversation tracking",
        description="Connect related emails into a single conversation context.",
        group=FeatureGroup.email,
        default=True,
    ),
    # --- Developer intelligence ---------------------------------------
    Feature(
        id="technical_detection",
        name="Technical email detection",
        description="Identify API issues, CI failures, bugs and development discussions.",
        group=FeatureGroup.developer,
        default=True,
        config=(
            ConfigField(
                key="interests",
                label="Technologies and projects of interest",
                kind="tags",
                default=[],
                help="Threads naming these are more likely to be flagged technical.",
            ),
        ),
    ),
    Feature(
        id="error_context",
        name="Error context extraction",
        description=("Extract stack traces, error messages, technologies and affected services."),
        group=FeatureGroup.developer,
        default=True,
        # You cannot pull error context out of threads nobody identified
        # as technical in the first place.
        requires=("technical_detection",),
    ),
    Feature(
        id="github_linking",
        name="GitHub context linking",
        description=("Connect relevant emails with GitHub issues, pull requests and repositories."),
        group=FeatureGroup.developer,
        default=False,
        requires=("technical_detection",),
        live=False,
        arrives_in_phase=13,
    ),
    Feature(
        id="technical_memory",
        name="Technical discussion memory",
        description="Keep track of ongoing technical discussions and their context.",
        group=FeatureGroup.developer,
        default=False,
        requires=("technical_detection",),
        live=False,
        arrives_in_phase=13,
    ),
    # --- Productivity --------------------------------------------------
    Feature(
        id="deadline_detection",
        name="Deadline detection",
        description="Identify deadlines and important dates from emails.",
        group=FeatureGroup.productivity,
        default=True,
        config=(
            ConfigField(
                key="remind_days_before",
                label="Remind me this many days before",
                kind="number",
                default=1,
                minimum=0,
                maximum=30,
            ),
        ),
    ),
    Feature(
        id="followup_reminders",
        name="Follow-up reminders",
        description="Detect conversations waiting for your response.",
        group=FeatureGroup.productivity,
        default=True,
        config=(
            ConfigField(
                key="days_before_reminder",
                label="Days before a reminder",
                kind="number",
                default=3,
                minimum=1,
                maximum=30,
            ),
        ),
    ),
    Feature(
        id="opportunity_discovery",
        name="Opportunity discovery",
        description="Identify internships, jobs, hackathons and relevant opportunities.",
        group=FeatureGroup.productivity,
        default=False,
        config=(
            ConfigField(
                key="preferred_roles",
                label="Preferred roles and technologies",
                kind="tags",
                default=[],
            ),
        ),
        live=False,
        arrives_in_phase=14,
    ),
    Feature(
        id="daily_briefing",
        name="Daily intelligence briefing",
        description="Prepare a personalized summary of what matters each day.",
        group=FeatureGroup.productivity,
        default=False,
        # A briefing of what matters needs something that decided what
        # matters.
        requires=("priority_detection",),
        live=False,
        arrives_in_phase=15,
    ),
    # --- Writing & communication ---------------------------------------
    Feature(
        id="personalized_replies",
        name="Personalized reply drafts",
        description="Generate replies matching your preferred writing style.",
        group=FeatureGroup.writing,
        default=True,
        config=(
            ConfigField(
                key="formality",
                label="Formality",
                kind="choice",
                default="match_me",
                options=(
                    ("match_me", "Match my style", "measured from your sent mail"),
                    ("formal", "Formal", "full sentences, no contractions"),
                    ("casual", "Casual", "short and direct"),
                ),
            ),
        ),
        live=False,
        arrives_in_phase=12,
    ),
    Feature(
        id="tone_adjustment",
        name="Tone adjustment",
        description="Rewrite messages to sound professional, friendly or concise.",
        group=FeatureGroup.writing,
        default=False,
        requires=("personalized_replies",),
        live=False,
        arrives_in_phase=12,
    ),
    Feature(
        id="quality_checker",
        name="Email quality checker",
        description="Check clarity, grammar and missing information before sending.",
        group=FeatureGroup.writing,
        default=False,
        requires=("personalized_replies",),
        live=False,
        arrives_in_phase=12,
    ),
    Feature(
        id="meeting_prep",
        name="Meeting preparation",
        description="Prepare context from emails before an upcoming meeting.",
        group=FeatureGroup.writing,
        default=False,
        live=False,
        arrives_in_phase=14,
    ),
)

_BY_ID: dict[str, Feature] = {feature.id: feature for feature in FEATURES}

#: Capabilities with no toggle, because switching them off would leave
#: nothing working. Named here so ``is_enabled`` can answer for them
#: without a default-to-true fallback that would hide a typo.
ALWAYS_ON: frozenset[str] = frozenset(
    {
        # The economic keystone. Every thread passes through it, and the
        # user-facing half of what it produces *is* toggleable --
        # priority_detection and smart_categorization.
        "triage",
        # The companion is a thing the user opens, not a thing that runs
        # on their mail. A toggle for it would be a toggle for a page.
        "ai_companion",
    }
)


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    label: str
    enabled: frozenset[str]

    def resolved(self) -> frozenset[str]:
        """The preset plus whatever its members require."""
        out = set(self.enabled)
        for _ in range(len(FEATURES)):
            grown = set(out)
            for feature_id in out:
                grown.update(_BY_ID[feature_id].requires)
            if grown == out:
                break
            out = grown
        return frozenset(out)


_MINIMAL = frozenset({"priority_detection", "instant_summaries", "smart_categorization"})
_PRODUCTIVITY = _MINIMAL | {
    "action_extraction",
    "deadline_detection",
    "followup_reminders",
    "personalized_replies",
}
_DEVELOPER = _PRODUCTIVITY | {
    "technical_detection",
    "error_context",
    "github_linking",
    "technical_memory",
}

PRESETS: tuple[Preset, ...] = (
    Preset("minimal", "Minimal", "Lightweight", _MINIMAL),
    Preset("productivity", "Productivity", "Recommended", frozenset(_PRODUCTIVITY)),
    Preset("developer", "Developer", "Developer-first", frozenset(_DEVELOPER)),
)


# ---------------------------------------------------------------------------
def get(feature_id: str) -> Feature:
    try:
        return _BY_ID[feature_id]
    except KeyError as exc:
        raise UnknownFeature(feature_id) from exc


def default_enabled() -> frozenset[str]:
    return frozenset(feature.id for feature in FEATURES if feature.default)


def dependents(feature_id: str) -> frozenset[str]:
    """Everything that cannot work once this is off, transitively."""
    out: set[str] = set()
    frontier = {feature_id}
    for _ in range(len(FEATURES)):
        found = {
            feature.id
            for feature in FEATURES
            if set(feature.requires) & frontier and feature.id not in out
        }
        if not found:
            break
        out |= found
        frontier = found
    return frozenset(out)


def requirements(feature_id: str) -> frozenset[str]:
    """Everything this needs, transitively."""
    out: set[str] = set()
    frontier = set(get(feature_id).requires)
    for _ in range(len(FEATURES)):
        if not frontier:
            break
        out |= frontier
        frontier = {need for dep in frontier for need in get(dep).requires if need not in out}
    return frozenset(out)


def resolve_enable(enabled: frozenset[str], feature_id: str) -> frozenset[str]:
    """Turn one on, and whatever it needs with it.

    The user is told what else moved. Silently enabling three other
    features because they were prerequisites is the kind of helpfulness
    that makes a settings screen untrustworthy.
    """
    get(feature_id)
    return enabled | {feature_id} | requirements(feature_id)


def resolve_disable(enabled: frozenset[str], feature_id: str) -> frozenset[str]:
    """Turn one off, and whatever depended on it."""
    get(feature_id)
    return enabled - {feature_id} - dependents(feature_id)


def validate_config(feature_id: str, raw: Any) -> dict[str, Any]:
    """Keep what the feature declares and nothing else.

    Unknown keys are dropped rather than stored. A config blob that
    accumulates settings nothing reads is a blob nobody can reason about,
    and it is also somewhere for an injected value to sit unnoticed.
    """
    feature = get(feature_id)
    incoming = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}

    for field_spec in feature.config:
        if field_spec.key not in incoming:
            out[field_spec.key] = field_spec.default
            continue
        value = incoming[field_spec.key]

        if field_spec.kind == "choice":
            allowed = {option[0] for option in field_spec.options}
            out[field_spec.key] = value if value in allowed else field_spec.default
        elif field_spec.kind == "number":
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = int(field_spec.default)
            if field_spec.minimum is not None:
                number = max(field_spec.minimum, number)
            if field_spec.maximum is not None:
                number = min(field_spec.maximum, number)
            out[field_spec.key] = number
        elif field_spec.kind == "tags":
            items = value if isinstance(value, list) else []
            out[field_spec.key] = [
                str(item).strip()[:40] for item in items[:20] if str(item).strip()
            ]
        else:  # pragma: no cover - the kinds are a closed set
            out[field_spec.key] = field_spec.default

    return out


#: The lists the screen renders, grouped and ordered as specified.
def grouped() -> list[tuple[FeatureGroup, str, list[Feature]]]:
    return [
        (group, label, [f for f in FEATURES if f.group is group]) for group, label in GROUPS.items()
    ]
