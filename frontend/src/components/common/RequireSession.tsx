import type { ReactNode } from "react";
import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/common/Skeleton";
import { useSession } from "@/stores/session";

/**
 * Checks the session once per page load.
 *
 * `attempted` rather than `status === "unknown"` is what gates the call. A
 * failed check leaves the status unknown, so keying the effect on the status
 * would re-run it on every render and turn one unreachable API into a
 * request loop. Retrying is a button, not a side effect.
 */
function useSessionOnce(): void {
  const attempted = useSession((state) => state.attempted);
  const load = useSession((state) => state.load);

  useEffect(() => {
    if (!attempted) void load();
  }, [attempted, load]);
}

/**
 * The gate in front of the application.
 *
 * The three-valued session status earns its keep here. "unknown" renders a
 * skeleton rather than redirecting, because treating "not checked yet" as
 * "signed out" would bounce every signed-in user to the welcome screen on
 * every page load.
 *
 * A network failure is also not a sign-out: it shows an error with a retry,
 * because sending someone to the welcome screen because their wifi blinked
 * loses whatever they were doing.
 */
export function RequireSession() {
  const status = useSession((state) => state.status);
  const error = useSession((state) => state.error);
  const load = useSession((state) => state.load);
  const location = useLocation();

  useSessionOnce();

  if (error && status === "unknown") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg">
        <ErrorState
          title="Could not reach Maail"
          description={error}
          onRetry={() => void load({ force: true })}
        />
      </div>
    );
  }

  if (status === "unknown") {
    return (
      <div role="status" aria-busy="true" className="flex min-h-dvh bg-bg">
        <span className="sr-only">Checking your session</span>
        <Skeleton className="h-full w-rail rounded-none" />
        <div className="flex-1 p-s3">
          <Skeleton className="h-8 w-48" />
        </div>
      </div>
    );
  }

  if (status === "anonymous") {
    return <Navigate to="/" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

/**
 * The root path. A signed-in person should not be shown a marketing page
 * they have already acted on.
 */
export function RootRoute({ welcome }: { welcome: ReactNode }) {
  const status = useSession((state) => state.status);

  useSessionOnce();

  if (status === "authenticated") return <Navigate to="/overview" replace />;
  return <>{welcome}</>;
}
