import { Check, ChevronDown, Clock, Link2, Loader2, Plus, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { featureSettings } from "@/services/api";
import type { ConfigFieldSchema, FeaturePreset, FeatureSettings, FeatureToggle } from "@/types/api";

/**
 * The seventeen toggles (08-ui-spec.md §10), rendered once and used at all
 * three entry points: onboarding step 3, Settings → AI preferences, and
 * the contextual suggestion.
 *
 * Three behaviours this component is responsible for.
 *
 * **A switch that moves on its own says so.** Turning off Technical email
 * detection turns off the three features that read its output. The
 * server returns what else changed and that is shown, because a settings
 * screen where switches flip silently is one nobody trusts.
 *
 * **A toggle that cannot do anything yet says that too.** Four of the
 * seventeen belong to capabilities that arrive in later phases. They
 * render as "arrives in phase N" rather than as a switch that changes a
 * row and nothing else.
 *
 * **Every change is saved immediately.** `Save configuration` in the
 * footer is therefore a confirmation, not a commit — the spec asks for
 * the button and the honest version of it is one that takes you onward
 * rather than one that pretends your clicks were provisional.
 */
export interface FeatureControlsProps {
  /** Onboarding shows presets first and a single forward action. */
  variant?: "settings" | "onboarding";
  onDone?: () => void;
  doneLabel?: string;
  className?: string;
}

function Switch({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-pill border transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        checked ? "border-violet bg-violet" : "border-border-strong bg-surface-sunken",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <span
        className={cn(
          "inline-block size-3.5 rounded-pill bg-surface transition-transform",
          checked ? "translate-x-[18px]" : "translate-x-[3px]",
        )}
      />
    </button>
  );
}

function ConfigField({
  field,
  value,
  onChange,
}: {
  field: ConfigFieldSchema;
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  const [draft, setDraft] = useState("");

  if (field.kind === "choice") {
    return (
      <fieldset className="flex flex-col gap-1">
        <legend className="text-2xs uppercase tracking-wide text-fg-subtle">{field.label}</legend>
        {field.options.map((option) => (
          <label
            key={option.value}
            className={cn(
              "flex cursor-pointer items-start gap-1.5 rounded-sm border px-1.5 py-1 transition-colors",
              value === option.value
                ? "border-violet/40 bg-violet-subtle"
                : "border-line bg-surface hover:bg-surface-sunken",
            )}
          >
            <input
              type="radio"
              className="sr-only"
              name={field.key}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span
              className={cn(
                "mt-1 inline-block size-2 shrink-0 rounded-pill border",
                value === option.value ? "border-violet bg-violet" : "border-border-strong",
              )}
            />
            <span className="min-w-0">
              <span className="block text-base text-fg">{option.label}</span>
              {/* The spec's exact words. "Balanced" alone is a different
                  promise from "important and time-sensitive emails". */}
              <span className="block text-2xs text-fg-subtle">{option.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>
    );
  }

  if (field.kind === "number") {
    return (
      <label className="flex flex-col gap-0.5">
        <span className="text-2xs uppercase tracking-wide text-fg-subtle">{field.label}</span>
        <input
          type="number"
          value={typeof value === "number" ? value : Number(field.default)}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          onChange={(event) => onChange(Number(event.target.value))}
          className="w-24 rounded-sm border border-line bg-surface px-1.5 py-1 text-base text-fg"
        />
      </label>
    );
  }

  const tags = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs uppercase tracking-wide text-fg-subtle">{field.label}</span>
      {field.help ? <span className="text-2xs text-fg-subtle">{field.help}</span> : null}
      <div className="flex flex-wrap items-center gap-1">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-pill border border-line bg-surface-sunken px-1.5 py-0.5 text-2xs text-fg"
          >
            {tag}
            <button
              type="button"
              aria-label={`Remove ${tag}`}
              onClick={() => onChange(tags.filter((item) => item !== tag))}
            >
              <X className="size-2.5" aria-hidden />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" || !draft.trim()) return;
            event.preventDefault();
            onChange([...tags, draft.trim()]);
            setDraft("");
          }}
          placeholder="Add and press Enter"
          aria-label={field.label}
          className="min-w-32 flex-1 rounded-sm border border-line bg-surface px-1.5 py-1 text-sm text-fg"
        />
      </div>
    </div>
  );
}

function FeatureRow({
  feature,
  busy,
  onToggle,
  onConfig,
  nameOf,
}: {
  feature: FeatureToggle;
  busy: boolean;
  onToggle: (feature: FeatureToggle) => void;
  onConfig: (feature: FeatureToggle, key: string, value: unknown) => void;
  nameOf: (id: string) => string;
}) {
  const [open, setOpen] = useState(false);
  const hasConfig = feature.config_schema.length > 0;

  return (
    <div className="rounded-sm border border-line bg-surface">
      <div className="flex items-start gap-2 px-s2 py-1.5">
        <Switch
          checked={feature.enabled}
          disabled={busy}
          label={feature.name}
          onChange={() => onToggle(feature)}
        />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-1 text-base text-fg">
            {feature.name}
            {!feature.live ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Badge variant="neutral">
                      <Clock className="size-2.5" aria-hidden />
                      phase {feature.arrives_in_phase}
                    </Badge>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  The switch is real and your choice is kept. The capability behind it arrives in
                  phase {feature.arrives_in_phase}.
                </TooltipContent>
              </Tooltip>
            ) : null}
          </p>
          <p className="text-sm text-fg-muted">{feature.description}</p>

          {feature.requires.length > 0 ? (
            <p className="mt-0.5 inline-flex items-center gap-1 text-2xs text-fg-subtle">
              <Link2 className="size-2.5" aria-hidden />
              Needs {feature.requires.map(nameOf).join(", ")}
            </p>
          ) : null}
        </div>

        {hasConfig && feature.enabled ? (
          <Button
            size="sm"
            variant="ghost"
            className="h-6 shrink-0 text-2xs"
            aria-expanded={open}
            onClick={() => setOpen((previous) => !previous)}
          >
            Configure
            <ChevronDown
              className={cn("size-3 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </Button>
        ) : null}
      </div>

      {open && hasConfig && feature.enabled ? (
        <div className="flex flex-col gap-s2 border-t border-line bg-surface-sunken px-s2 py-s2">
          {feature.config_schema.map((field) => (
            <ConfigField
              key={field.key}
              field={field}
              value={feature.config[field.key] ?? field.default}
              onChange={(next) => onConfig(feature, field.key, next)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PresetCard({
  preset,
  busy,
  onApply,
}: {
  preset: FeaturePreset;
  busy: boolean;
  onApply: (preset: FeaturePreset) => void;
}) {
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => onApply(preset)}
      className={cn(
        "flex min-w-44 flex-1 flex-col gap-0.5 rounded-sm border px-s2 py-1.5 text-left transition-colors",
        preset.active
          ? "border-violet/40 bg-violet-subtle"
          : "border-line bg-surface hover:bg-surface-sunken",
      )}
    >
      <span className="flex items-center gap-1 font-brand text-base font-semibold text-fg">
        {preset.name}
        {preset.active ? <Check className="size-3 text-violet" aria-hidden /> : null}
      </span>
      <span className="text-2xs text-fg-subtle">{preset.label}</span>
      <span className="text-2xs text-fg-muted">
        {preset.features.length} feature{preset.features.length === 1 ? "" : "s"}
      </span>
    </button>
  );
}

export function FeatureControls({
  variant = "settings",
  onDone,
  doneLabel = "Save configuration",
  className,
}: FeatureControlsProps) {
  const [data, setData] = useState<FeatureSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [moved, setMoved] = useState<string[]>([]);

  const load = useCallback(
    () =>
      featureSettings
        .read()
        .then(setData)
        .catch((caught: unknown) =>
          setError(caught instanceof Error ? caught.message : "Could not load your settings"),
        ),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const nameOf = useCallback(
    (id: string) =>
      data?.groups.flatMap((group) => group.features).find((feature) => feature.id === id)?.name ??
      id,
    [data],
  );

  const toggle = (feature: FeatureToggle) => {
    setBusy(feature.id);
    setMoved([]);
    void featureSettings
      .set(feature.id, { enabled: !feature.enabled })
      .then((change) => {
        setData(change.settings);
        setMoved(change.also_changed);
      })
      .catch((caught: unknown) =>
        setError(caught instanceof Error ? caught.message : "Could not save that"),
      )
      .finally(() => setBusy(null));
  };

  const changeConfig = (feature: FeatureToggle, key: string, value: unknown) => {
    const next = { ...feature.config, [key]: value };
    // Optimistic, so a radio button does not wait for a round trip. The
    // server's answer replaces this either way.
    setData((previous) =>
      previous
        ? {
            ...previous,
            groups: previous.groups.map((group) => ({
              ...group,
              features: group.features.map((item) =>
                item.id === feature.id ? { ...item, config: next } : item,
              ),
            })),
          }
        : previous,
    );
    void featureSettings
      .set(feature.id, { config: next })
      .then((change) => setData(change.settings));
  };

  const applyPreset = (preset: FeaturePreset) => {
    setBusy(preset.id);
    setMoved([]);
    void featureSettings
      .preset(preset.id)
      .then((change) => {
        setData(change.settings);
        setMoved(change.also_changed);
      })
      .finally(() => setBusy(null));
  };

  const enableAll = () => {
    setBusy("all");
    setMoved([]);
    void featureSettings
      .enableAll()
      .then((change) => setData(change.settings))
      .finally(() => setBusy(null));
  };

  if (error && !data) return <ErrorState description={error} onRetry={() => void load()} />;

  if (!data) {
    return (
      <div className={cn("flex flex-col gap-1.5", className)}>
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  return (
    <section className={cn("flex flex-col gap-s3", className)}>
      <header>
        <h2 className="font-brand text-xl font-semibold text-fg">Personalize your intelligence</h2>
        <p className="mt-1 text-base text-fg-muted">
          Choose what Maail should handle for you. You can change these anytime.
        </p>
      </header>

      {/* Presets first, and especially during onboarding: nobody should
          have to configure seventeen switches to get started. */}
      <div className="flex flex-col gap-1.5">
        <h3 className="text-2xs uppercase tracking-wide text-fg-subtle">Start from a preset</h3>
        <div className="flex flex-wrap gap-1.5">
          {data.presets.map((preset) => (
            <PresetCard
              key={preset.id}
              preset={preset}
              busy={busy !== null}
              onApply={applyPreset}
            />
          ))}
        </div>
      </div>

      {moved.length > 0 ? (
        <p
          role="status"
          className="rounded-sm border border-ai-border bg-ai px-s2 py-1.5 text-sm text-ai-fg"
        >
          {/* A switch that moved on its own has to say so. */}
          Also changed: {moved.map(nameOf).join(", ")}.
        </p>
      ) : null}

      {data.groups.map((group) => (
        <div key={group.id} className="flex flex-col gap-1.5">
          <h3 className="font-brand text-base font-semibold text-fg">{group.label}</h3>
          {group.features.map((feature) => (
            <FeatureRow
              key={feature.id}
              feature={feature}
              busy={busy !== null}
              onToggle={toggle}
              onConfig={changeConfig}
              nameOf={nameOf}
            />
          ))}
        </div>
      ))}

      <footer className="flex flex-wrap items-center gap-s2 border-t border-line pt-s2">
        <span className="flex-1 text-base text-fg">
          <span className="font-semibold tabular-nums">{data.enabled_count}</span> of{" "}
          {data.total_count} features enabled
        </span>
        <Button variant="ghost" size="sm" disabled={busy !== null} onClick={enableAll}>
          {busy === "all" ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
          Enable all
        </Button>
        <Button size="sm" onClick={() => onDone?.()}>
          {variant === "onboarding" ? doneLabel : "Save configuration"}
        </Button>
      </footer>

      {variant === "settings" ? (
        <p className="inline-flex items-start gap-1.5 text-2xs text-fg-subtle">
          <Sparkles className="mt-0.5 size-3 shrink-0" aria-hidden />
          Changes save as you make them. Turning something off stops Maail doing it from now on;
          anything it already worked out stays where it is.
        </p>
      ) : null}
    </section>
  );
}

export default FeatureControls;
