import type { Meta, StoryObj } from "@storybook/react";
import { CalendarClock, Inbox, Sparkles } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/common/Skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * The four base states the spec requires: skeleton, empty, error, offline
 * (08-ui-spec.md §4). Offline has its own story because it is a banner rather
 * than a region.
 */
const meta: Meta = {
  title: "Design system/Base states",
  parameters: { layout: "padded" },
};
export default meta;

export const Skeletons: StoryObj = {
  render: () => (
    <div className="flex max-w-xl flex-col gap-s3">
      <Card>
        <CardHeader>
          <CardTitle>Email list, syncing</CardTitle>
        </CardHeader>
        <CardContent>
          <SkeletonRegion label="Loading your mail" className="flex flex-col gap-s2">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="flex gap-s2">
                <Skeleton className="size-9 rounded-pill" />
                <div className="flex-1">
                  <Skeleton className="h-3.5 w-1/3" />
                  <Skeleton className="mt-1.5 h-3 w-4/5" />
                </div>
                <Skeleton className="h-3 w-10" />
              </div>
            ))}
          </SkeletonRegion>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Thread body</CardTitle>
        </CardHeader>
        <CardContent>
          <SkeletonText lines={5} />
        </CardContent>
      </Card>
    </div>
  ),
};

export const Empty: StoryObj = {
  render: () => (
    <div className="grid max-w-5xl gap-s3 lg:grid-cols-2">
      <Card>
        <EmptyState
          icon={Inbox}
          title="Nothing left to read"
          description="Everything in this view has been handled. New mail appears here as it syncs."
        />
      </Card>
      <Card>
        <EmptyState
          icon={CalendarClock}
          title="No deadlines found"
          description="Maail only lists a deadline when a sender named one. It will not invent a date to fill this space."
          action={{ label: "Review action items", onClick: () => undefined }}
        />
      </Card>
      <Card>
        <EmptyState
          icon={Sparkles}
          title="Nothing to read yet"
          description="The panel follows whatever you have selected."
        />
      </Card>
      <Card>
        <EmptyState
          title="No connected account"
          description="Connect Gmail to start. Maail reads your mail; it never sends without asking."
          action={{ label: "Connect Gmail", onClick: () => undefined }}
          secondaryAction={{ label: "What does it access?", onClick: () => undefined }}
        />
      </Card>
    </div>
  ),
};

export const Errors: StoryObj = {
  render: () => (
    <div className="grid max-w-5xl gap-s3 lg:grid-cols-2">
      <Card>
        <ErrorState onRetry={() => undefined} />
      </Card>
      <Card>
        <ErrorState
          title="Could not reach Gmail"
          description="Google returned an error while syncing. Your existing mail is unaffected."
          requestId="9f2c41e8b7a3"
          onRetry={() => undefined}
        />
      </Card>
    </div>
  ),
};

export const Offline: StoryObj = {
  parameters: { layout: "fullscreen" },
  render: () => (
    <div className="border-b border-warning-border bg-warning text-warning-fg">
      <div className="flex items-center justify-center gap-2 px-s2 py-1.5 text-sm">
        <span>You are offline. Mail already synced stays readable; nothing will send.</span>
      </div>
    </div>
  ),
};
