"""Screen 11: the feature controls, the presets, and the settings sections.

Nothing here calls a model, and that is a blocking gate rather than a
coincidence: *no model call to evaluate whether a toggle is on* (phase
11). Reading and writing settings is rows, and the import graph makes it
impossible for this module to do anything else -- ``app/api`` may not
import an LLM client at all.

Two behaviours the endpoints exist to guarantee:

**Disabling stops future processing and keeps what is already there.** A
toggle is not a delete button. Turning off Instant summaries means no new
summary is produced; the one already written stays visible, marked with
the version of the thread it was made from.

**Dependencies move together, and the user is told.** Turning off
Technical email detection also turns off the three features that read its
output. The response says which, so the screen can show it rather than
having three switches silently flip.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.modules.features import registry
from app.modules.features import service as features
from app.modules.features.registry import UnknownFeature

router = APIRouter(prefix="/settings", tags=["settings"])
log = get_logger(__name__)

#: The nine sections of screen 11, in the spec's order. Returned to the
#: client rather than hard-coded there, so the list has one home.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("account", "Account", "Profile, authentication"),
    ("email_accounts", "Email accounts", "Gmail connection, synchronization"),
    ("ai_preferences", "AI preferences", "Model, response style"),
    ("memory", "Memory", "Inspect and manage personal context"),
    ("agents", "Agents", "Enable/disable and permissions"),
    ("integrations", "Integrations", "GitHub, Calendar"),
    ("privacy", "Privacy", "Data access, retention, deletion"),
    ("appearance", "Appearance", "Light, dark, system"),
    ("notifications", "Notifications", "Priority and deadline alerts"),
)


class ConfigOption(BaseModel):
    value: str
    label: str
    #: The spec's exact wording, carried to the screen rather than
    #: paraphrased there. "Balanced" without "important and
    #: time-sensitive emails" is a different promise.
    detail: str


class ConfigFieldOut(BaseModel):
    key: str
    label: str
    kind: str
    default: Any
    options: list[ConfigOption] = Field(default_factory=list)
    minimum: int | None = None
    maximum: int | None = None
    help: str = ""


class FeatureOut(BaseModel):
    id: str
    name: str
    description: str
    group: str
    enabled: bool
    default: bool
    #: What this needs, and what needs this. Both directions, because the
    #: screen has to explain a switch that moved on its own.
    requires: list[str] = Field(default_factory=list)
    required_by: list[str] = Field(default_factory=list)
    #: False for a toggle whose capability has not been built yet. Shown
    #: as "arrives in phase N" rather than as a switch that does nothing.
    live: bool = True
    arrives_in_phase: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    config_schema: list[ConfigFieldOut] = Field(default_factory=list)


class GroupOut(BaseModel):
    id: str
    label: str
    features: list[FeatureOut]


class PresetOut(BaseModel):
    id: str
    name: str
    label: str
    features: list[str]
    #: True when the user's current selection is exactly this preset.
    active: bool = False


class SectionOut(BaseModel):
    id: str
    label: str
    controls: str


class SettingsOut(BaseModel):
    groups: list[GroupOut]
    presets: list[PresetOut]
    sections: list[SectionOut]
    enabled_count: int
    total_count: int


class SetFeature(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class FeatureChange(BaseModel):
    """What actually moved, so the screen can say so."""

    settings: SettingsOut
    #: Ids that changed state as a consequence rather than by being
    #: clicked. Empty on a simple toggle.
    also_changed: list[str] = Field(default_factory=list)


def _build(config: features.FeatureConfig) -> SettingsOut:
    groups = [
        GroupOut(
            id=group.value,
            label=label,
            features=[FeatureOut(**features.describe(feature, config)) for feature in items],
        )
        for group, label, items in registry.grouped()
    ]

    current = config.enabled
    presets = [
        PresetOut(
            id=preset.id,
            name=preset.name,
            label=preset.label,
            features=sorted(preset.resolved()),
            active=current == preset.resolved(),
        )
        for preset in registry.PRESETS
    ]

    return SettingsOut(
        groups=groups,
        presets=presets,
        sections=[
            SectionOut(id=sid, label=label, controls=controls) for sid, label, controls in SECTIONS
        ],
        enabled_count=config.count(),
        total_count=len(registry.FEATURES),
    )


@router.get("", response_model=SettingsOut, summary="Every toggle and its state")
async def read_settings(auth: AuthContext) -> SettingsOut:
    """Rows and a list in Git. No model, by construction."""
    return _build(await features.load(auth.session, auth.user_id))


@router.put(
    "/features/{feature_id}",
    response_model=FeatureChange,
    dependencies=[Depends(require_csrf)],
    summary="Turn one feature on or off, or change its configuration",
)
async def set_feature(feature_id: str, body: SetFeature, auth: AuthContext) -> FeatureChange:
    before = await features.load(auth.session, auth.user_id)
    try:
        after = await features.set_feature(
            auth.session,
            auth.user_id,
            feature_id,
            enabled=body.enabled,
            config=body.config,
        )
    except UnknownFeature as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such feature") from exc

    moved = sorted((before.enabled ^ after.enabled) - {feature_id})
    if moved:
        log.info("features.cascade", touched=feature_id, also=moved)

    return FeatureChange(settings=_build(after), also_changed=moved)


@router.post(
    "/presets/{preset_id}",
    response_model=FeatureChange,
    dependencies=[Depends(require_csrf)],
    summary="Apply a preset",
)
async def apply_preset(preset_id: str, auth: AuthContext) -> FeatureChange:
    """The toggles move together, which is the point of a preset.

    Per-feature configuration survives: a preset says which features run,
    not how they run, and wiping someone's urgency sensitivity because
    they clicked Developer would be a surprise.
    """
    before = await features.load(auth.session, auth.user_id)
    try:
        after = await features.apply_preset(auth.session, auth.user_id, preset_id)
    except UnknownFeature as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such preset") from exc

    return FeatureChange(
        settings=_build(after), also_changed=sorted(before.enabled ^ after.enabled)
    )


@router.post(
    "/features/enable-all",
    response_model=FeatureChange,
    dependencies=[Depends(require_csrf)],
    summary="Enable everything",
)
async def enable_all(auth: AuthContext) -> FeatureChange:
    before = await features.load(auth.session, auth.user_id)
    after = before
    for feature in registry.FEATURES:
        after = await features.set_feature(auth.session, auth.user_id, feature.id, enabled=True)
    return FeatureChange(
        settings=_build(after), also_changed=sorted(before.enabled ^ after.enabled)
    )
