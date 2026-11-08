import { AlertTriangle, ArrowRight, Check, Loader2, Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Wordmark } from "@/components/layout/Wordmark";
import { Button } from "@/components/ui/button";
import { auth } from "@/services/api";
import { useAccounts } from "@/stores/accounts";
import { useSession } from "@/stores/session";

/**
 * Screen 02 — Account connection (08-ui-spec.md §9).
 *
 *     maail.                         Step 1 of 3
 *
 *            Let's connect your inbox.
 *
 *            Maail needs access to your email
 *            to understand your communication.
 *
 *            ┌─────────────────────────────┐
 *            │       Google Gmail          │
 *            │     Connect account →       │
 *            └─────────────────────────────┘
 *
 *            What Maail can do:
 *            ✓ Read and organize emails
 *            ✓ Generate summaries
 *            ✓ Prepare response drafts
 *
 *            Permissions and privacy →
 *
 * The copy is the spec's, unchanged. What the architecture adds is the
 * handling of the two ways this screen is reached after a redirect: with a
 * connected account, or with a reason it failed.
 */

/**
 * The callback redirects here with a reason code rather than a provider
 * message, because a provider error body can echo the authorization code or
 * the client secret. Turning the code into a sentence is this screen's job.
 */
const REASONS: Record<string, string> = {
  access_denied:
    "You chose not to give Maail access. Nothing was connected, and nothing was stored.",
  flow_missing: "That sign-in attempt could not be matched to this browser. Start again from here.",
  state_mismatch:
    "That sign-in link did not match the one this browser started. Start again from here.",
  state_expired_or_replayed:
    "That sign-in link had already been used, or it expired. Start again from here.",
  state_purpose_mismatch: "That sign-in link was for something else. Start again from here.",
  malformed_callback: "Google sent back an incomplete response. Try once more.",
  exchange_failed: "Google would not complete the connection. Try once more.",
  provider_error: "Google reported an error. Try once more in a moment.",
  grant_rejected:
    "Google refused the connection. Remove Maail from your Google account permissions, then connect again.",
  reconnect_requires_session: "Sign in first, then reconnect the account from Settings.",
  account_not_found: "That account is no longer connected to Maail.",
  account_mismatch:
    "That is a different Google account. Reconnect with the address you originally connected, or connect the new one separately.",
};

const CAPABILITIES = [
  "Read and organize emails",
  "Generate summaries",
  "Prepare response drafts",
] as const;

export function ConnectPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const sessionStatus = useSession((state) => state.status);
  const loadSession = useSession((state) => state.load);
  const items = useAccounts((state) => state.items);
  const loadAccounts = useAccounts((state) => state.load);

  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reason = params.get("error");
  const justConnected = params.get("connected") === "1";

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  useEffect(() => {
    if (sessionStatus === "authenticated") void loadAccounts();
  }, [sessionStatus, loadAccounts]);

  const connected = items.find((account) => account.status === "active");

  const begin = () => {
    setError(null);
    setStarting(true);
    void auth
      .startGoogle()
      .then(({ authorize_url }) => window.location.assign(authorize_url))
      .catch((caught: unknown) => {
        setStarting(false);
        setError(caught instanceof Error ? caught.message : "Could not start the connection.");
      });
  };

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center justify-between px-s3 py-s2">
        <Wordmark />
        <span className="text-sm text-fg-muted">Step 1 of 3</span>
      </header>

      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center px-s3 pb-s6">
        <h1 className="font-brand text-3xl font-bold text-fg">Let&rsquo;s connect your inbox.</h1>
        <p className="mt-s2 max-w-[40ch] text-md text-fg-muted">
          Maail needs access to your email to understand your communication.
        </p>

        {reason ? (
          <div
            role="alert"
            className="mt-s3 flex items-start gap-2 rounded-md border border-warning-border bg-warning px-s2 py-2 text-sm text-warning-fg"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{REASONS[reason] ?? "That did not work. Try once more."}</span>
          </div>
        ) : null}

        {connected ? (
          <div className="mt-s3 rounded-md border border-success-border bg-success p-s2 text-success-fg">
            <p className="flex items-center gap-2 font-medium">
              <Check className="size-4 shrink-0" aria-hidden />
              {justConnected ? "Connected" : "Already connected"}
            </p>
            <p className="mt-1 text-sm opacity-90">{connected.email}</p>
          </div>
        ) : (
          <div className="mt-s3 rounded-md border border-line bg-surface p-s3 text-center">
            <p className="flex items-center justify-center gap-2 font-brand text-lg font-semibold text-fg">
              <Mail className="size-4 text-violet" aria-hidden />
              Google Gmail
            </p>
            <Button className="mt-s2 w-full sm:w-auto" onClick={begin} disabled={starting}>
              {starting ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Connect account
              {starting ? null : <ArrowRight aria-hidden />}
            </Button>
            {error ? (
              <p role="alert" className="mt-s1 text-sm text-danger-fg">
                {error}
              </p>
            ) : null}
          </div>
        )}

        <section className="mt-s4">
          <h2 className="font-brand text-base font-semibold text-fg">What Maail can do:</h2>
          <ul className="mt-s1 flex flex-col gap-1.5">
            {CAPABILITIES.map((capability) => (
              <li key={capability} className="flex items-center gap-2 text-base text-fg-muted">
                <Check className="size-4 shrink-0 text-violet" aria-hidden />
                {capability}
              </li>
            ))}
          </ul>
        </section>

        <Link
          to="/permissions"
          className="mt-s3 inline-flex items-center gap-1 self-start text-base text-violet underline-offset-4 hover:underline"
        >
          Permissions and privacy
          <ArrowRight className="size-3.5" aria-hidden />
        </Link>

        {connected ? (
          <Button
            variant="secondary"
            className="mt-s4 self-start"
            onClick={() => void navigate("/onboarding/personalize")}
          >
            Continue
            <ArrowRight aria-hidden />
          </Button>
        ) : null}
      </main>
    </div>
  );
}

export default ConnectPage;
