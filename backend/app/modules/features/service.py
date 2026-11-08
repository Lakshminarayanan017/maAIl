"""Read and write a user's feature configuration, cached correctly.

Every agent invocation asks whether its feature is on, so this is on the
hot path and has to be cheap. It also has to be *right*, which is the
harder half: the API and the worker are separate processes with separate
memory, so a cache that only invalidates on local writes would keep a
disabled feature running in the worker until something evicted it.

So the cache is keyed on a watermark rather than on a clock. A cached
config remembers the ``max(updated_at)`` it was loaded at, and every
lookup does one index-only probe of that value. If it has not moved, the
cached object is returned untouched; if it has, the config is reloaded.
One small query in the common case, and no window in which a process
acts on a setting the user has already changed.

A TTL would have been simpler and wrong in a way nobody would notice
until someone turned a feature off and it kept running for half a minute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.features import registry
from app.modules.features.registry import ALWAYS_ON, Feature, UnknownFeature

log = get_logger(__name__)

__all__ = [
    "FeatureConfig",
    "apply_preset",
    "config_for",
    "invalidate",
    "is_enabled",
    "load",
    "set_feature",
]


@dataclass(frozen=True)
class FeatureConfig:
    """One user's effective settings: the defaults, overlaid with their rows."""

    user_id: UUID
    enabled: frozenset[str]
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The ``max(updated_at)`` this was loaded at. None when the user has
    #: no rows, which is its own distinguishable watermark.
    watermark: datetime | None = None

    def is_on(self, feature_id: str) -> bool:
        if feature_id in ALWAYS_ON:
            return True
        # Raises for an id no feature claims. A typo in a FEATURE_ID
        # constant must not read as "enabled".
        registry.get(feature_id)
        return feature_id in self.enabled

    def config(self, feature_id: str) -> dict[str, Any]:
        feature = registry.get(feature_id)
        return {**feature.default_config(), **self.configs.get(feature_id, {})}

    def count(self) -> int:
        return len(self.enabled)


_WATERMARK = text("SELECT max(updated_at) FROM user_features WHERE user_id = :user_id")

_ROWS = text(
    """
    SELECT feature_id, enabled, config, updated_at
      FROM user_features
     WHERE user_id = :user_id
    """
)

_UPSERT = text(
    """
    INSERT INTO user_features (user_id, feature_id, enabled, config, updated_at)
    VALUES (:user_id, :feature_id, :enabled, CAST(:config AS jsonb), now())
    ON CONFLICT (user_id, feature_id) DO UPDATE SET
        enabled = excluded.enabled,
        config = excluded.config,
        updated_at = now()
    """
)

#: Per-process. Small and bounded by the number of users one process
#: serves between restarts.
_CACHE: dict[UUID, FeatureConfig] = {}


def invalidate(user_id: UUID | None = None) -> None:
    """Drop the local copy. The watermark covers other processes."""
    if user_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(user_id, None)


async def load(session: AsyncSession, user_id: UUID) -> FeatureConfig:
    """This user's effective configuration, from cache when it is current."""
    watermark = await session.scalar(_WATERMARK, {"user_id": str(user_id)})

    cached = _CACHE.get(user_id)
    if cached is not None and cached.watermark == watermark:
        return cached

    rows = (await session.execute(_ROWS, {"user_id": str(user_id)})).all()

    # Start from the defaults in Git, then apply what the user touched.
    # A user with no rows gets exactly the current defaults, which is why
    # signup writes nothing.
    enabled = set(registry.default_enabled())
    configs: dict[str, dict[str, Any]] = {}

    for row in rows:
        feature_id = str(row[0])
        try:
            registry.get(feature_id)
        except UnknownFeature:
            # A feature that has been removed from the list. The row is
            # left alone -- deleting a user's setting because a release
            # renamed something is worse than ignoring it.
            log.info("features.unknown_row_ignored", feature_id=feature_id)
            continue
        if bool(row[1]):
            enabled.add(feature_id)
        else:
            enabled.discard(feature_id)
        if row[2]:
            configs[feature_id] = dict(row[2])

    resolved = FeatureConfig(
        user_id=user_id,
        enabled=frozenset(enabled),
        configs=configs,
        watermark=watermark,
    )
    _CACHE[user_id] = resolved
    return resolved


async def is_enabled(session: AsyncSession, user_id: UUID, feature_id: str) -> bool:
    """The question every agent asks before it runs. No model involved."""
    return (await load(session, user_id)).is_on(feature_id)


async def config_for(session: AsyncSession, user_id: UUID, feature_id: str) -> dict[str, Any]:
    return (await load(session, user_id)).config(feature_id)


async def set_feature(
    session: AsyncSession,
    user_id: UUID,
    feature_id: str,
    *,
    enabled: bool | None = None,
    config: Any = None,
) -> FeatureConfig:
    """Change one toggle, and whatever the dependency graph implies.

    Returns the whole resolved configuration rather than the one row,
    because turning something off can turn three other things off and the
    caller has to be able to show the user what moved.
    """
    registry.get(feature_id)
    current = await load(session, user_id)

    if enabled is None:
        target = current.enabled
    elif enabled:
        target = registry.resolve_enable(current.enabled, feature_id)
    else:
        target = registry.resolve_disable(current.enabled, feature_id)

    writes: dict[str, bool] = {}
    for candidate in registry.FEATURES:
        now_on = candidate.id in target
        if now_on != (candidate.id in current.enabled):
            writes[candidate.id] = now_on
    # The toggle the user actually touched is always written, even when
    # it did not change state -- a config edit alone still needs a row.
    writes.setdefault(feature_id, feature_id in target)

    for changed, state in writes.items():
        stored = (
            registry.validate_config(changed, config)
            if changed == feature_id and config is not None
            else current.configs.get(changed, {})
        )
        await _write(session, user_id, changed, state, stored)

    invalidate(user_id)
    return await load(session, user_id)


async def apply_preset(session: AsyncSession, user_id: UUID, preset_id: str) -> FeatureConfig:
    """Set every toggle at once. The toggles move together, as specified."""
    preset = next((item for item in registry.PRESETS if item.id == preset_id), None)
    if preset is None:
        raise UnknownFeature(preset_id)

    target = preset.resolved()
    current = await load(session, user_id)

    for feature in registry.FEATURES:
        await _write(
            session,
            user_id,
            feature.id,
            feature.id in target,
            # Per-feature configuration is the user's and survives a
            # preset. A preset says which features run, not how.
            current.configs.get(feature.id, {}),
        )

    invalidate(user_id)
    log.info("features.preset_applied", preset=preset_id, enabled=len(target))
    return await load(session, user_id)


async def _write(
    session: AsyncSession,
    user_id: UUID,
    feature_id: str,
    enabled: bool,
    config: dict[str, Any],
) -> None:
    import json

    await session.execute(
        _UPSERT,
        {
            "user_id": str(user_id),
            "feature_id": feature_id,
            "enabled": enabled,
            "config": json.dumps(config or {}),
        },
    )


def describe(feature: Feature, config: FeatureConfig) -> dict[str, Any]:
    """One feature as the settings screen needs it."""
    return {
        "id": feature.id,
        "name": feature.name,
        "description": feature.description,
        "group": feature.group.value,
        "enabled": config.is_on(feature.id),
        "default": feature.default,
        "requires": sorted(feature.requires),
        "required_by": sorted(registry.dependents(feature.id)),
        "live": feature.live,
        "arrives_in_phase": feature.arrives_in_phase,
        "config": config.config(feature.id) if feature.config else {},
        "config_schema": [
            {
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "default": item.default,
                "options": [
                    {"value": value, "label": label, "detail": detail}
                    for value, label, detail in item.options
                ],
                "minimum": item.minimum,
                "maximum": item.maximum,
                "help": item.help,
            }
            for item in feature.config
        ],
    }
