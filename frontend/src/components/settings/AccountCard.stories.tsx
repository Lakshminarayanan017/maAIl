import type { Meta, StoryObj } from "@storybook/react";

import { AccountCard } from "@/components/settings/AccountCard";
import type { Account } from "@/types/api";

/**
 * Every state a connection can be in. Storybook is where mocked data belongs
 * (execution plan, rule 1), and a status card is only worth reviewing when
 * all of its states are side by side.
 */
const base: Account = {
  id: "acc-1",
  email: "nishanth@example.com",
  provider: "gmail",
  status: "active",
  granted_scopes: [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
  ],
  missing_scopes: [],
  refresh_expires_at: new Date(Date.now() + 6 * 86_400_000).toISOString(),
  needs_reconnect: false,
  expires_soon: false,
  connected_at: new Date(Date.now() - 86_400_000).toISOString(),
  last_error: null,
  sync_progress: { total: null, done: 0, last_synced_at: null },
  disconnected_at: null,
  purge_after: null,
};

const meta: Meta<typeof AccountCard> = {
  title: "Settings/AccountCard",
  component: AccountCard,
  parameters: { layout: "padded" },
  args: {
    account: base,
    onReconnect: () => undefined,
    onDisconnect: () => undefined,
  },
  decorators: [
    (Story) => (
      <div className="max-w-xl">
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof AccountCard>;

export const Connected: Story = {};

export const ExpiringSoon: Story = {
  args: {
    account: {
      ...base,
      expires_soon: true,
      refresh_expires_at: new Date(Date.now() + 86_400_000).toISOString(),
    },
  },
};

export const NeedsReconnecting: Story = {
  args: {
    account: {
      ...base,
      status: "reauth_required",
      needs_reconnect: true,
      last_error: "Google will not renew this connection. Reconnect the account.",
    },
  },
};

export const PermissionDeclined: Story = {
  args: {
    account: {
      ...base,
      status: "error",
      missing_scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
      last_error: "Missing permission: https://www.googleapis.com/auth/gmail.readonly",
    },
  },
};

export const Disconnected: Story = {
  args: {
    account: {
      ...base,
      status: "disconnected",
      refresh_expires_at: null,
      disconnected_at: new Date().toISOString(),
      purge_after: new Date(Date.now() + 30 * 86_400_000).toISOString(),
    },
  },
};
