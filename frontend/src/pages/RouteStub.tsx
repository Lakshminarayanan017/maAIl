import { Compass } from "lucide-react";
import { useLocation } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { Badge } from "@/components/ui/badge";
import { navItemFor } from "@/components/layout/navigation";

/**
 * What a route renders before its data source exists.
 *
 * Rule 1 of the execution plan: no fake data in the application. A screen
 * ships when the thing that feeds it is real. Until then the route says which
 * phase fills it, which is the difference between "not built yet" and
 * "broken".
 */
export function RouteStub() {
  const { pathname } = useLocation();
  const item = navItemFor(pathname);

  if (!item) {
    return (
      <EmptyState
        icon={Compass}
        title="No such page"
        description="That route does not exist in Maail."
      />
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-s3 py-s6">
      <EmptyState icon={item.icon} title={item.label} description={item.purpose} className="py-s3">
        <div className="flex flex-wrap items-center justify-center gap-s1">
          {item.screen ? <Badge variant="neutral">Screen {item.screen}</Badge> : null}
          <Badge variant="violet">Phase {item.phase}</Badge>
        </div>
      </EmptyState>
      <p className="max-w-md text-center text-sm text-fg-muted">
        The shell, the design tokens and the three regions are real. This screen stays empty until
        its data source exists, rather than showing a sample of what it will look like.
      </p>
    </div>
  );
}
