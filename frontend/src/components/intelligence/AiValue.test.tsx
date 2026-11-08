import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AiValue } from "@/components/intelligence/AiValue";

const EVIDENCE = [{ messageId: "m-1", charStart: 0, charEnd: 10, quote: "by Friday" }];

describe("AiValue", () => {
  it("renders a value that has evidence", () => {
    render(<AiValue value="Due Friday" status="ready" evidence={EVIDENCE} />);
    expect(screen.getByText("Due Friday")).toBeInTheDocument();
  });

  it("refuses to render a value with no evidence", () => {
    // The whole point of the component: an unsourced claim is an absence,
    // never an answer.
    render(<AiValue value="High priority" status="ready" />);
    expect(screen.queryByText("High priority")).toBeNull();
    expect(screen.getByText("Not determined")).toBeInTheDocument();
  });

  it("opens the evidence span on request", async () => {
    const user = userEvent.setup();
    render(<AiValue value="Due Friday" status="ready" evidence={EVIDENCE} />);

    await user.click(screen.getByRole("button", { name: /source/i }));

    expect(screen.getByText("by Friday")).toBeInTheDocument();
    expect(screen.getByText("Maail worked this out")).toBeInTheDocument();
  });

  it("says analysing rather than showing nothing", () => {
    render(<AiValue value="x" status="running" label="Deadline" />);
    expect(screen.getByRole("status")).toHaveTextContent(/analysing/i);
  });

  it("explains a failure and offers a retry", async () => {
    const user = userEvent.setup();
    let retried = false;
    render(
      <AiValue
        value="x"
        status="failed"
        error="schema mismatch"
        onRetry={() => (retried = true)}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("schema mismatch");
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(retried).toBe(true);
  });

  it("distinguishes a disabled capability from a failed one", () => {
    render(<AiValue value="x" status="skipped_disabled" />);
    expect(screen.getByText(/turned off in settings/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders nothing at all when the capability does not apply", () => {
    const { container } = render(<AiValue value="x" status="not_applicable" />);
    expect(container).toBeEmptyDOMElement();
  });
});
