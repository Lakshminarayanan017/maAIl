import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReconnectBanner } from "@/components/common/ReconnectBanner";
import { AccountCard } from "@/components/settings/AccountCard";
import { useAccounts } from "@/stores/accounts";
import type { Account } from "@/types/api";

function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "acc-1",
    email: "person@example.com",
    provider: "gmail",
    status: "active",
    granted_scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    missing_scopes: [],
    refresh_expires_at: null,
    needs_reconnect: false,
    expires_soon: false,
    connected_at: "2026-03-01T00:00:00Z",
    last_error: null,
    sync_progress: { total: null, done: 0, last_synced_at: null },
    disconnected_at: null,
    purge_after: null,
    ...overrides,
  };
}

beforeEach(() => {
  useAccounts.setState({ items: [], loading: false, error: null });
});

describe("ReconnectBanner", () => {
  it("stays out of the way while every account is healthy", () => {
    useAccounts.setState({ items: [account()] });
    const { container } = render(<ReconnectBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("appears when an account needs re-authorising", () => {
    useAccounts.setState({
      items: [account({ status: "reauth_required", needs_reconnect: true })],
    });
    render(<ReconnectBanner />);

    expect(screen.getByRole("status")).toHaveTextContent("person@example.com");
    expect(screen.getByRole("status")).toHaveTextContent(/needs reconnecting/i);
  });

  it("says what is not happening while it shows", () => {
    useAccounts.setState({
      items: [account({ status: "reauth_required", needs_reconnect: true })],
    });
    render(<ReconnectBanner />);
    expect(screen.getByRole("status")).toHaveTextContent(/new mail is not arriving/i);
  });

  it("cannot be dismissed", () => {
    // Persistent and non-dismissable while reauth_required
    // (09-execution-plan.md, phase 1). A banner someone can close is a
    // stalled mailbox that becomes a mystery a week later.
    useAccounts.setState({
      items: [account({ status: "reauth_required", needs_reconnect: true })],
    });
    render(<ReconnectBanner />);

    const buttons = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(buttons).toEqual(["Reconnect"]);
    expect(screen.queryByRole("button", { name: /dismiss|close|hide/i })).toBeNull();
  });

  it("starts the reconnect flow", async () => {
    const user = userEvent.setup();
    const reconnect = vi.fn().mockResolvedValue(undefined);
    useAccounts.setState({
      items: [account({ status: "reauth_required", needs_reconnect: true })],
      reconnect,
    });

    render(<ReconnectBanner />);
    await user.click(screen.getByRole("button", { name: /reconnect/i }));

    expect(reconnect).toHaveBeenCalledWith("acc-1");
  });
});

describe("AccountCard", () => {
  const noop = () => undefined;

  it("shows the address and a connected status", () => {
    render(<AccountCard account={account()} onReconnect={noop} onDisconnect={noop} />);
    expect(screen.getByText("person@example.com")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("warns before the authorisation expires, not after", () => {
    const inTwoDays = new Date(Date.now() + 2 * 86_400_000).toISOString();
    render(
      <AccountCard
        account={account({ refresh_expires_at: inTwoDays, expires_soon: true })}
        onReconnect={noop}
        onDisconnect={noop}
      />,
    );
    expect(screen.getByText(/Authorisation expires/)).toBeInTheDocument();
    expect(screen.getByText(/in 2 days/)).toBeInTheDocument();
  });

  it("explains a declined permission in terms of the fix", () => {
    render(
      <AccountCard
        account={account({
          status: "error",
          missing_scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
        })}
        onReconnect={noop}
        onDisconnect={noop}
      />,
    );
    expect(screen.getByText(/leave every box ticked/i)).toBeInTheDocument();
  });

  it("reassures that reconnecting keeps what Maail already knows", () => {
    render(
      <AccountCard
        account={account({ status: "reauth_required", needs_reconnect: true })}
        onReconnect={noop}
        onDisconnect={noop}
      />,
    );
    expect(screen.getByText(/keeps everything Maail already knows/i)).toBeInTheDocument();
  });

  it("asks before disconnecting, and says what happens to the mail", async () => {
    const user = userEvent.setup();
    const onDisconnect = vi.fn();
    render(<AccountCard account={account()} onReconnect={noop} onDisconnect={onDisconnect} />);

    await user.click(screen.getByRole("button", { name: /^disconnect$/i }));

    expect(screen.getByText(/Mail is deleted after 30 days/)).toBeInTheDocument();
    expect(onDisconnect).not.toHaveBeenCalled();
  });

  it("offers an immediate delete as well as the 30-day default", async () => {
    const user = userEvent.setup();
    const onDisconnect = vi.fn();
    render(<AccountCard account={account()} onReconnect={noop} onDisconnect={onDisconnect} />);

    await user.click(screen.getByRole("button", { name: /^disconnect$/i }));
    await user.click(screen.getByRole("button", { name: /disconnect and delete now/i }));

    expect(onDisconnect).toHaveBeenCalledWith("acc-1", "now");
  });

  it("can be backed out of", async () => {
    const user = userEvent.setup();
    const onDisconnect = vi.fn();
    render(<AccountCard account={account()} onReconnect={noop} onDisconnect={onDisconnect} />);

    await user.click(screen.getByRole("button", { name: /^disconnect$/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onDisconnect).not.toHaveBeenCalled();
    expect(screen.queryByText(/Mail is deleted after 30 days/)).toBeNull();
  });
});
