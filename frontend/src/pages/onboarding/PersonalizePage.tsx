import { ArrowRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Wordmark } from "@/components/layout/Wordmark";
import { FeatureControls } from "@/components/settings/FeatureControls";

/**
 * Onboarding step 3 — entry point A for the feature controls.
 *
 * > during onboarding, after connecting Gmail, with recommended presets
 * > (08-ui-spec.md §10)
 *
 * The presets are the whole reason this screen is tolerable at step 3 of
 * 3. Seventeen switches in front of someone who has just connected their
 * mailbox is a wall; three cards, one of them marked Recommended, is a
 * decision. The switches are there underneath for whoever wants them.
 *
 * Skipping is a real option and says what happens: the defaults are ten
 * features, and Settings is one click away forever.
 */
export function PersonalizePage() {
  const navigate = useNavigate();
  const go = () => void navigate("/overview");

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center justify-between px-s3 py-s2">
        <Wordmark />
        <span className="text-sm text-fg-muted">Step 3 of 3</span>
      </header>

      <main className="mx-auto w-full max-w-2xl flex-1 px-s3 pb-s6">
        <FeatureControls variant="onboarding" doneLabel="Save and continue" onDone={go} />

        <button
          type="button"
          onClick={go}
          className="mt-s3 inline-flex items-center gap-1 text-base text-fg-muted underline-offset-4 hover:underline"
        >
          Skip — use the defaults
          <ArrowRight className="size-3.5" aria-hidden />
        </button>
      </main>
    </div>
  );
}

export default PersonalizePage;
