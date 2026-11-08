import { create } from "zustand";

import { ApiError, auth } from "@/services/api";
import type { SessionUser } from "@/types/api";

/**
 * Who is signed in, if anyone.
 *
 * `status` is three-valued on purpose. "unknown" is not "signed out": the
 * difference is a redirect to the welcome screen on first paint, before the
 * session has been checked, which would log the user out every refresh.
 *
 * Two things stop it hammering the API. Concurrent calls share one request,
 * and a failed check does not retry itself — a check that leaves the status
 * "unknown" would otherwise re-trigger the effect that called it, which is a
 * request loop against a server that is already unhappy.
 */
export type SessionStatus = "unknown" | "authenticated" | "anonymous";

interface SessionState {
  status: SessionStatus;
  user: SessionUser | null;
  error: string | null;
  checking: boolean;
  /** True once a check has completed or failed, successful or not. */
  attempted: boolean;
  load: (options?: { force?: boolean }) => Promise<void>;
  signOut: () => Promise<void>;
}

let inflight: Promise<void> | null = null;

export const useSession = create<SessionState>((set, get) => ({
  status: "unknown",
  user: null,
  error: null,
  checking: false,
  attempted: false,

  load: async ({ force = false } = {}) => {
    const { checking, attempted } = get();
    if (checking && inflight) return inflight;
    if (attempted && !force) return;

    set({ checking: true, error: force ? null : get().error });

    inflight = (async () => {
      try {
        const response = await auth.session();
        set({ status: "authenticated", user: response.user, error: null });
      } catch (error) {
        if (error instanceof ApiError && error.isUnauthenticated) {
          set({ status: "anonymous", user: null, error: null });
          return;
        }
        // A network failure is not a sign-out. Saying "anonymous" here would
        // bounce someone to the welcome screen because their wifi blinked.
        set({ error: error instanceof Error ? error.message : "Could not reach Maail" });
      } finally {
        set({ checking: false, attempted: true });
        inflight = null;
      }
    })();

    return inflight;
  },

  signOut: async () => {
    await auth.signOut();
    set({ status: "anonymous", user: null, error: null, attempted: true });
  },
}));
