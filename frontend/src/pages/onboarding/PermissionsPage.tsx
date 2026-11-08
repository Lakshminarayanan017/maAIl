import { ArrowLeft, Check, Lock, X } from "lucide-react";
import { Link } from "react-router-dom";

import { Wordmark } from "@/components/layout/Wordmark";
import { Separator } from "@/components/ui/separator";

/**
 * The scope explanation page.
 *
 * > clear explanation of every requested scope · **separate authorization
 * > for sending emails**
 * > (08-ui-spec.md, screen 02 requirements)
 *
 * Every scope the app asks Google for is named here in its raw form and in
 * plain words. The raw strings are listed on purpose: anyone can compare
 * them against the consent screen Google shows, and against the code.
 *
 * The "what Maail never asks for" list is the other half of that promise.
 * It is the one that matters, and it is the one nobody writes.
 */

interface Scope {
  raw: string;
  title: string;
  plain: string;
}

const REQUESTED: Scope[] = [
  {
    raw: "https://www.googleapis.com/auth/gmail.readonly",
    title: "Read your Gmail",
    plain:
      "Maail reads your messages, their subjects, senders, labels and attachment names so it can group them into threads and understand them. Read-only: with this permission alone it is not possible to send, reply, delete or change anything in your mailbox.",
  },
  {
    raw: "https://www.googleapis.com/auth/userinfo.email",
    title: "See your email address",
    plain:
      "Which Google account this is. It becomes the address on your Maail account, so you can tell two connected mailboxes apart.",
  },
  {
    raw: "openid",
    title: "Confirm it is you",
    plain:
      "The standard sign-in check. It tells Maail that Google verified this account, and nothing else about you.",
  },
];

const NEVER: string[] = [
  "Send, reply to or forward mail on your behalf",
  "Delete, archive or relabel anything in your mailbox",
  "Read your Google Drive, Calendar, Contacts or Photos",
  "Share your mail with anyone, or use it to train a model",
];

export function PermissionsPage() {
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex items-center justify-between px-s3 py-s2">
        <Wordmark />
        <Link
          to="/onboarding/connect"
          className="flex items-center gap-1 text-sm text-violet underline-offset-4 hover:underline"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Back
        </Link>
      </header>

      <main className="mx-auto w-full max-w-2xl flex-1 px-s3 pb-s6">
        <h1 className="font-brand text-3xl font-bold text-fg">Permissions and privacy</h1>
        <p className="mt-s2 text-md text-fg-muted">
          Three permissions, listed exactly as Google will show them. Nothing here is summarised
          away.
        </p>

        <section className="mt-s4">
          <h2 className="font-brand text-lg font-semibold text-fg">What Maail asks for</h2>
          <ul className="mt-s2 flex flex-col gap-s2">
            {REQUESTED.map((scope) => (
              <li key={scope.raw} className="rounded-md border border-line bg-surface p-s2">
                <p className="flex items-center gap-2 font-medium text-fg">
                  <Check className="size-4 shrink-0 text-violet" aria-hidden />
                  {scope.title}
                </p>
                <p className="mt-1 text-base text-fg-muted">{scope.plain}</p>
                <code className="mt-1.5 block break-all font-mono text-2xs text-fg-subtle">
                  {scope.raw}
                </code>
              </li>
            ))}
          </ul>
        </section>

        <Separator className="my-s4" />

        <section>
          <h2 className="font-brand text-lg font-semibold text-fg">What Maail never asks for</h2>
          <ul className="mt-s2 flex flex-col gap-1.5">
            {NEVER.map((item) => (
              <li key={item} className="flex items-start gap-2 text-base text-fg-muted">
                <X className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
                {item}
              </li>
            ))}
          </ul>
        </section>

        <div className="mt-s4 flex items-start gap-2 rounded-md border border-ai-border bg-ai p-s2 text-ai-fg">
          <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="text-base">
            <p className="font-medium">Sending is a separate decision.</p>
            <p className="mt-1 opacity-90">
              Maail can draft a reply, but drafting and sending are different permissions. Sending
              is never granted here. When you first ask Maail to send something, it will ask for
              that permission on its own, and every send is shown to you for approval before it
              leaves.
            </p>
          </div>
        </div>

        <section className="mt-s4">
          <h2 className="font-brand text-lg font-semibold text-fg">What happens to your mail</h2>
          <ul className="mt-s2 flex list-disc flex-col gap-1.5 pl-5 text-base text-fg-muted">
            <li>
              It is stored in Maail&rsquo;s own database, separated from every other account at the
              database level rather than by application code.
            </li>
            <li>
              Access tokens are encrypted before they are written, under a key that can be rotated
              without re-encrypting your mail.
            </li>
            <li>
              Message bodies are stored as text with quoted history stripped. The original HTML is
              fetched from Gmail when you open a message, not kept.
            </li>
            <li>
              Disconnecting deletes the stored credential immediately. Your mail is deleted thirty
              days later, or straight away if you ask.
            </li>
          </ul>
        </section>

        <Link
          to="/onboarding/connect"
          className="mt-s4 inline-block text-base text-violet underline-offset-4 hover:underline"
        >
          Back to connecting your inbox
        </Link>
      </main>
    </div>
  );
}

export default PermissionsPage;
