import type { Meta, StoryObj } from "@storybook/react";

import { AiBlockSkeleton, AiValue, CapabilityChip } from "@/components/intelligence/AiValue";
import type { AiStatus } from "@/components/intelligence/AiValue";

/**
 * Every AI state on one page. This is the phase 4 demo: the status
 * vocabulary every later screen depends on, reviewable before any agent
 * exists to produce it.
 */
const meta: Meta = {
  title: "Intelligence/AiValue",
  parameters: { layout: "padded" },
};
export default meta;

const EVIDENCE = [
  {
    messageId: "8f14e45f-ea8c-4b24-9b5a-1d2c3e4f5a6b",
    charStart: 42,
    charEnd: 96,
    quote: "Could you send the draft by Friday?",
  },
];

const STATUSES: AiStatus[] = [
  "pending",
  "running",
  "ready",
  "failed",
  "skipped_disabled",
  "skipped_budget",
];

export const EveryState: StoryObj = {
  render: () => (
    <div className="flex max-w-2xl flex-col gap-s3">
      <section>
        <h3 className="mb-s1 font-brand text-md font-semibold text-fg">Values</h3>
        <div className="flex flex-col gap-s2">
          {STATUSES.map((status) => (
            <div key={status} className="flex items-center gap-s2">
              <code className="w-36 shrink-0 font-mono text-2xs text-fg-subtle">{status}</code>
              <AiValue
                value="Needs a reply by Friday"
                status={status}
                evidence={EVIDENCE}
                label="Deadline"
                error="The model returned something that did not match the schema"
                onRetry={() => undefined}
              />
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-s1 font-brand text-md font-semibold text-fg">
          Ready, but with nothing behind it
        </h3>
        <p className="mb-s1 text-sm text-fg-muted">
          A value with no evidence renders as an absence, never as an answer.
        </p>
        <AiValue value="High priority" status="ready" />
      </section>

      <section>
        <h3 className="mb-s1 font-brand text-md font-semibold text-fg">Sources</h3>
        <div className="flex flex-col gap-s2">
          {(["agent", "user_rule", "user_override", "integration"] as const).map((source) => (
            <AiValue
              key={source}
              value="Technical"
              status="ready"
              source={source}
              evidence={EVIDENCE}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-s1 font-brand text-md font-semibold text-fg">Capability chips</h3>
        <div className="flex flex-wrap gap-1">
          {STATUSES.map((status) => (
            <CapabilityChip key={status} capability="summary" status={status} />
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-s1 font-brand text-md font-semibold text-fg">Block skeletons</h3>
        <div className="grid gap-s2 sm:grid-cols-3">
          <AiBlockSkeleton kind="summary" />
          <AiBlockSkeleton kind="deadline" />
          <AiBlockSkeleton kind="actions" />
        </div>
      </section>
    </div>
  ),
};
