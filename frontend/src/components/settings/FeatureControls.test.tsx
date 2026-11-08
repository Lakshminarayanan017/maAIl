import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeatureControls } from "@/components/settings/FeatureControls";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { FeatureSettings, FeatureToggle } from "@/types/api";

/**
 * Three things the screen must do that the server cannot do for it.
 *
 * Say when a switch moved on its own · never offer a switch for a
 * capability that does not exist yet · show the exact wording the spec
 * fixes, because "Balanced" alone is a different promise from "important
 * and time-sensitive emails".
 */
const { read, set } = vi.hoisted(() => ({ read: vi.fn(), set: vi.fn() }));

vi.mock("@/services/api", () => ({
  featureSettings: {
    read,
    set,
    preset: vi.fn(),
    enableAll: vi.fn(),
  },
}));

function feature(overrides: Partial<FeatureToggle> = {}): FeatureToggle {
  return {
    id: "priority_detection",
    name: "Priority detection",
    description: "Identify urgent, important and time-sensitive emails.",
    group: "email_intelligence",
    enabled: true,
    default: true,
    requires: [],
    required_by: [],
    live: true,
    arrives_in_phase: null,
    config: { sensitivity: "balanced" },
    config_schema: [
      {
        key: "sensitivity",
        label: "Urgency sensitivity",
        kind: "choice",
        default: "balanced",
        options: [
          { value: "strict", label: "Strict", detail: "only genuinely urgent emails" },
          {
            value: "balanced",
            label: "Balanced",
            detail: "important and time-sensitive emails",
          },
          {
            value: "sensitive",
            label: "Sensitive",
            detail: "include potentially important emails",
          },
        ],
        minimum: null,
        maximum: null,
        help: "",
      },
    ],
    ...overrides,
  };
}

function settings(features: FeatureToggle[]): FeatureSettings {
  return {
    groups: [{ id: "email_intelligence", label: "Email intelligence", features }],
    presets: [
      {
        id: "productivity",
        name: "Productivity",
        label: "Recommended",
        features: ["priority_detection"],
        active: false,
      },
    ],
    sections: [],
    enabled_count: features.filter((item) => item.enabled).length,
    total_count: features.length,
  };
}

function mount() {
  return render(
    <TooltipProvider>
      <FeatureControls />
    </TooltipProvider>,
  );
}

describe("FeatureControls", () => {
  beforeEach(() => {
    read.mockReset();
    set.mockReset();
  });

  it("shows the spec's exact wording in the configuration drawer", async () => {
    read.mockResolvedValue(settings([feature()]));
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: /configure/i }));

    expect(screen.getByText("only genuinely urgent emails")).toBeInTheDocument();
    expect(screen.getByText("important and time-sensitive emails")).toBeInTheDocument();
    expect(screen.getByText("include potentially important emails")).toBeInTheDocument();
  });

  it("says which other switches moved", async () => {
    const technical = feature({
      id: "technical_detection",
      name: "Technical email detection",
      description: "Identify API issues, CI failures, bugs and development discussions.",
      config: {},
      config_schema: [],
    });
    const dependent = feature({
      id: "error_context",
      name: "Error context extraction",
      description: "Extract stack traces, error messages, technologies and services.",
      requires: ["technical_detection"],
      config: {},
      config_schema: [],
    });

    read.mockResolvedValue(settings([technical, dependent]));
    set.mockResolvedValue({
      settings: settings([
        { ...technical, enabled: false },
        { ...dependent, enabled: false },
      ]),
      also_changed: ["error_context"],
    });

    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("switch", { name: "Technical email detection" }));

    // Silently flipping a second switch is how a settings screen stops
    // being trusted.
    await waitFor(() =>
      expect(screen.getByText(/Also changed: Error context extraction/)).toBeInTheDocument(),
    );
  });

  it("marks a toggle whose capability has not been built", async () => {
    read.mockResolvedValue(
      settings([
        feature({
          id: "github_linking",
          name: "GitHub context linking",
          description: "Connect relevant emails with GitHub issues and pull requests.",
          enabled: false,
          default: false,
          live: false,
          arrives_in_phase: 13,
          config: {},
          config_schema: [],
        }),
      ]),
    );
    mount();

    expect(await screen.findByText("phase 13")).toBeInTheDocument();
  });

  it("counts what is enabled", async () => {
    read.mockResolvedValue(
      settings([feature(), feature({ id: "instant_summaries", enabled: false })]),
    );
    mount();

    expect(await screen.findByText("1")).toBeInTheDocument();
    expect(screen.getByText(/of 2 features enabled/)).toBeInTheDocument();
  });
});
