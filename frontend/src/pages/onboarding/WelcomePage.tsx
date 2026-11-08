import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Wordmark } from "@/components/layout/Wordmark";
import { Button } from "@/components/ui/button";
import { auth } from "@/services/api";

/**
 * Screen 01 — Welcome & onboarding (08-ui-spec.md §9).
 *
 *     maail.                                      Sign in
 *
 *                   Your inbox deserves
 *                       a brain.
 *
 *            Understand more. Manage less.
 *
 *            Your personal AI companion for
 *            smarter email and development work.
 *
 *                  [ Get started → ]
 *
 *             Privacy-first · You stay in control
 *
 *                   [ Product preview ]
 *
 * Every line of copy here is the spec's, unchanged. "Get started" and
 * "Sign in" both begin the same Google flow in v1, because connecting a
 * mailbox is how an account comes into existence -- there is no password to
 * register and nothing to sign in to before one exists.
 *
 * The product preview is a slot, not a mock. Rule 1: no fake data in the
 * running app. It fills in when there is a real product to show.
 */
export function WelcomePage() {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const begin = () => {
    setError(null);
    setStarting(true);
    void auth
      .startGoogle()
      .then(({ authorize_url }) => {
        // A whole-page navigation. Google refuses to render consent in an
        // iframe, and a popup is the thing browsers block.
        window.location.assign(authorize_url);
      })
      .catch((caught: unknown) => {
        setStarting(false);
        setError(
          caught instanceof Error
            ? caught.message
            : "Could not start sign-in. Try again in a moment.",
        );
      });
  };

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center justify-between px-s3 py-s2">
        <Wordmark />
        <Button variant="ghost" size="sm" onClick={begin} disabled={starting}>
          Sign in
        </Button>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-s3 pb-s6 text-center">
        <h1 className="max-w-[14ch] text-balance font-brand text-4xl font-bold leading-[1.05] text-fg sm:text-5xl">
          Your inbox deserves a brain.
        </h1>

        <p className="mt-s3 font-brand text-xl font-semibold text-fg">
          Understand more. Manage less.
        </p>

        <p className="mt-s2 max-w-[34ch] text-balance text-md text-fg-muted">
          Your personal AI companion for smarter email and development work.
        </p>

        <Button size="lg" className="mt-s4" onClick={begin} disabled={starting}>
          {starting ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Get started
          {starting ? null : <ArrowRight aria-hidden />}
        </Button>

        {error ? (
          <p role="alert" className="mt-s2 max-w-sm text-sm text-danger-fg">
            {error}
          </p>
        ) : null}

        <p className="mt-s3 flex items-center gap-1.5 text-sm text-fg-muted">
          <ShieldCheck className="size-3.5 text-violet" aria-hidden />
          Privacy-first
          <span aria-hidden className="text-fg-subtle">
            ·
          </span>
          You stay in control
        </p>

        <Link
          to="/permissions"
          className="mt-1 text-sm text-violet underline-offset-4 hover:underline"
        >
          What Maail can access
        </Link>

        {/*
          The product-preview slot. Deliberately empty: a screenshot of an
          inbox that does not exist yet is exactly the fake data rule 1 of the
          execution plan forbids.
        */}
        <div
          className="mt-s6 flex h-56 w-full max-w-3xl items-center justify-center rounded-lg border border-dashed border-line bg-surface/60 text-sm text-fg-subtle"
          aria-hidden
          data-testid="product-preview"
        >
          Product preview
        </div>
      </main>

      <footer className="px-s3 pb-s3 text-center text-xs text-fg-subtle">
        Maail reads your mail to understand it. It never sends anything without asking.
      </footer>
    </div>
  );
}

export default WelcomePage;
