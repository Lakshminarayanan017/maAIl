import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProvenanceLegend, ProvenanceValue } from "@/components/intelligence/Provenance";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Evidence } from "@/types/api";

/**
 * The UI half of phase 8's gate.
 *
 * The backend drops spans that do not resolve; this is the other end —
 * what the panel does when it is handed a value with nothing behind it.
 * It says "not determined". Showing the claim anyway would make the
 * backend's work pointless, and the two halves have to agree.
 */
function mount(node: React.ReactNode) {
  return render(<TooltipProvider>{node}</TooltipProvider>);
}

const QUOTED: Evidence[] = [
  { message_id: "m1", char_start: 4, char_end: 28, quote: "confirm by Friday" },
];

const UNQUOTABLE: Evidence[] = [{ message_id: "m1", char_start: 4, char_end: 28, quote: null }];

describe("ProvenanceValue", () => {
  it("renders a stated value when it can be quoted", () => {
    mount(
      <ProvenanceValue provenance="stated" evidence={QUOTED}>
        Branch: development
      </ProvenanceValue>,
    );
    expect(screen.getByText("Branch: development")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /source/i })).toBeInTheDocument();
  });

  it("refuses to render a stated value with no evidence", () => {
    mount(<ProvenanceValue provenance="stated">Branch: development</ProvenanceValue>);
    expect(screen.queryByText("Branch: development")).not.toBeInTheDocument();
    expect(screen.getByText("Not determined")).toBeInTheDocument();
  });

  it("refuses a stated value whose evidence has no quotable words", () => {
    mount(
      <ProvenanceValue provenance="stated" evidence={UNQUOTABLE}>
        Branch: development
      </ProvenanceValue>,
    );
    expect(screen.getByText("Not determined")).toBeInTheDocument();
  });

  it("still renders an interpretation without a span, labelled as one", () => {
    // An interpretation is honest about being a conclusion, so it does
    // not need a quotation to exist -- it only may not pose as one.
    mount(<ProvenanceValue provenance="interpreted">The build failed on main</ProvenanceValue>);
    expect(screen.getByText("The build failed on main")).toBeInTheDocument();
    expect(screen.getByLabelText("Maail worked this out")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /source/i })).not.toBeInTheDocument();
  });

  it("marks the three provenance classes differently", () => {
    mount(<ProvenanceLegend />);
    for (const label of [
      "Said in the email",
      "Maail worked this out",
      "From elsewhere in your mail",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("gives only the AI class the reserved lavender", () => {
    mount(<ProvenanceLegend />);
    // Soft lavender is reserved for AI-derived values (08-ui-spec.md §2),
    // so a fact lifted from the email must not wear it.
    expect(screen.getByLabelText("Maail worked this out").className).toContain("bg-ai");
    expect(screen.getByLabelText("Said in the email").className).not.toContain("bg-ai");
    expect(screen.getByLabelText("From elsewhere in your mail").className).not.toContain("bg-ai");
  });
});
