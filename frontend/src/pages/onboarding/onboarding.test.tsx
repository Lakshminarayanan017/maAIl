import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectPage } from "@/pages/onboarding/ConnectPage";
import { PermissionsPage } from "@/pages/onboarding/PermissionsPage";
import { WelcomePage } from "@/pages/onboarding/WelcomePage";
import { useAccounts } from "@/stores/accounts";
import { useSession } from "@/stores/session";
import { navigations } from "@/test/setup";
import type { Account } from "@/types/api";

/**
 * Screens 01 and 02 are locked copy. These assert the exact sentences from
 * 08-ui-spec.md §9, so a well-meant rewrite of "Understand more. Manage
 * less." fails rather than ships.
 */

function renderAt(path: string, element: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path.split("?")[0]} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

const ACTIVE: Account = {
  id: "acc-1",
  email: "person@example.com",
  provider: "gmail",
  status: "active",
  granted_scopes: [],
  missing_scopes: [],
  refresh_expires_at: null,
  needs_reconnect: false,
  expires_soon: false,
  connected_at: "2026-03-01T00:00:00Z",
  last_error: null,
  sync_progress: { total: null, done: 0, last_synced_at: null },
  disconnected_at: null,
  purge_after: null,
};

beforeEach(() => {
  useSession.setState({ status: "anonymous", user: null, error: null });
  useAccounts.setState({ items: [], loading: false, error: null });
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("no network in a unit test")));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Screen 01 - Welcome", () => {
  it("shows the locked hero copy, word for word", () => {
    renderAt("/", <WelcomePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Your inbox deserves a brain." }),
    ).toBeInTheDocument();
    expect(screen.getByText("Understand more. Manage less.")).toBeInTheDocument();
    expect(
      screen.getByText("Your personal AI companion for smarter email and development work."),
    ).toBeInTheDocument();
  });

  it("offers Get started and Sign in", () => {
    renderAt("/", <WelcomePage />);
    expect(screen.getByRole("button", { name: /get started/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("carries the privacy line", () => {
    renderAt("/", <WelcomePage />);
    expect(screen.getByText(/Privacy-first/)).toBeInTheDocument();
    expect(screen.getByText(/You stay in control/)).toBeInTheDocument();
  });

  it("keeps the product preview as an empty slot, not a mocked screenshot", () => {
    renderAt("/", <WelcomePage />);
    const slot = screen.getByTestId("product-preview");
    expect(slot).toHaveTextContent("Product preview");
    expect(within(slot).queryByRole("img")).toBeNull();
  });

  it("asks the API for a consent URL when Get started is pressed", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ authorize_url: "https://accounts.google.test/x" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderAt("/", <WelcomePage />);
    await user.click(screen.getByRole("button", { name: /get started/i }));

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/google/start"),
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    // A whole-page navigation: Google will not render consent in an iframe,
    // and a popup is what browsers block.
    expect(navigations).toContain("https://accounts.google.test/x");
  });

  it("says so when sign-in cannot be started", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Google OAuth is not configured." }), {
          status: 503,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    renderAt("/", <WelcomePage />);
    await user.click(screen.getByRole("button", { name: /get started/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not configured");
  });
});

describe("Screen 02 - Account connection", () => {
  it("shows the step label and the locked copy", () => {
    renderAt("/onboarding/connect", <ConnectPage />);

    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Let’s connect your inbox." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Maail needs access to your email to understand your communication."),
    ).toBeInTheDocument();
  });

  it("shows the Google Gmail card with Connect account", () => {
    renderAt("/onboarding/connect", <ConnectPage />);
    expect(screen.getByText("Google Gmail")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect account/i })).toBeInTheDocument();
  });

  it("lists exactly the three capability lines from the spec", () => {
    renderAt("/onboarding/connect", <ConnectPage />);
    expect(screen.getByText("What Maail can do:")).toBeInTheDocument();
    for (const line of [
      "Read and organize emails",
      "Generate summaries",
      "Prepare response drafts",
    ]) {
      expect(screen.getByText(line)).toBeInTheDocument();
    }
  });

  it("links to permissions and privacy", () => {
    renderAt("/onboarding/connect", <ConnectPage />);
    expect(screen.getByRole("link", { name: /permissions and privacy/i })).toHaveAttribute(
      "href",
      "/permissions",
    );
  });

  it("shows the connected account instead of the card once there is one", () => {
    useSession.setState({ status: "authenticated", user: null, error: null });
    useAccounts.setState({ items: [ACTIVE], loading: false, error: null });

    renderAt("/onboarding/connect", <ConnectPage />);

    expect(screen.getByText("person@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect account/i })).toBeNull();
    expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
  });
});

describe("Screen 02 - callback failures", () => {
  function renderWithError(reason: string) {
    return render(
      <MemoryRouter initialEntries={[`/onboarding/connect?error=${reason}`]}>
        <Routes>
          <Route path="/onboarding/connect" element={<ConnectPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("explains a declined consent as a choice, not a fault", () => {
    renderWithError("access_denied");
    expect(screen.getByRole("alert")).toHaveTextContent(/chose not to give Maail access/i);
  });

  it("explains a replayed state in terms of what to do next", () => {
    renderWithError("state_expired_or_replayed");
    expect(screen.getByRole("alert")).toHaveTextContent(/start again/i);
  });

  it("explains an account mismatch", () => {
    renderWithError("account_mismatch");
    expect(screen.getByRole("alert")).toHaveTextContent(/different Google account/i);
  });

  it("falls back to something useful for a code it does not know", () => {
    renderWithError("something_new");
    expect(screen.getByRole("alert")).toHaveTextContent(/try once more/i);
  });
});

describe("The permissions page", () => {
  it("names every requested scope in its raw form", () => {
    renderAt("/permissions", <PermissionsPage />);

    expect(screen.getByText("https://www.googleapis.com/auth/gmail.readonly")).toBeInTheDocument();
    expect(screen.getByText("https://www.googleapis.com/auth/userinfo.email")).toBeInTheDocument();
    expect(screen.getByText("openid")).toBeInTheDocument();
  });

  it("states that sending is a separate authorisation", () => {
    renderAt("/permissions", <PermissionsPage />);
    expect(screen.getByText("Sending is a separate decision.")).toBeInTheDocument();
  });

  it("says what Maail never asks for", () => {
    renderAt("/permissions", <PermissionsPage />);
    expect(screen.getByText("What Maail never asks for")).toBeInTheDocument();
    expect(screen.getByText("Send, reply to or forward mail on your behalf")).toBeInTheDocument();
  });
});
