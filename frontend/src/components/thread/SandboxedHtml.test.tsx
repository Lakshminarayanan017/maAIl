import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SandboxedHtml } from "@/components/thread/SandboxedHtml";

/**
 * The third layer of the defence (the server's sanitiser and the sandbox
 * being the first two). These assertions are cheap and the thing they
 * guard is expensive to get wrong, so they are worth having even in a
 * phase where testing was kept thin.
 */
function frame(html: string, imagesLoaded = false): HTMLIFrameElement {
  render(<SandboxedHtml html={html} imagesLoaded={imagesLoaded} />);
  return screen.getByTitle<HTMLIFrameElement>("Message");
}

describe("SandboxedHtml", () => {
  it("gives the iframe no capabilities at all", () => {
    // The empty string is the most restrictive value: no scripts, no
    // forms, no top navigation, and an opaque origin.
    expect(frame("<p>hi</p>").getAttribute("sandbox")).toBe("");
  });

  it("sends no referrer", () => {
    expect(frame("<p>hi</p>").getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("blocks every network source by default", () => {
    const doc = frame("<p>hi</p>").getAttribute("srcdoc") ?? "";
    expect(doc).toContain("default-src 'none'");
    expect(doc).toContain("script-src 'none'");
    expect(doc).toContain("form-action 'none'");
  });

  it("allows only data: images until the reader asks", () => {
    // So a remote src that somehow survived the sanitiser still cannot
    // reach the network and report that the message was opened.
    const doc = frame('<img src="https://track.test/p.gif">').getAttribute("srcdoc") ?? "";
    expect(doc).toContain("img-src data:");
    expect(doc).not.toContain("img-src https:");
  });

  it("allows https images once the reader has asked", () => {
    const doc = frame('<img src="https://ok.test/p.png">', true).getAttribute("srcdoc") ?? "";
    expect(doc).toContain("img-src https: data:");
  });

  it("renders the message content it was given", () => {
    const doc = frame("<p>Hello there</p>").getAttribute("srcdoc") ?? "";
    expect(doc).toContain("Hello there");
  });
});
