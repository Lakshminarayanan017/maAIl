import { useMemo } from "react";

/**
 * Sender HTML, rendered inside a sandbox it cannot get out of.
 *
 * Three layers, because any one of them can be wrong:
 *
 * 1. The server sanitised it against an allowlist (`nh3`).
 * 2. `sandbox=""` — the most restrictive value there is. No scripts, no
 *    forms, no plugins, no top-level navigation, and a unique opaque
 *    origin, so even a surviving script has no cookies and no DOM of ours
 *    to read.
 * 3. A CSP inside the document, which is what stops a surviving `<img>`
 *    from reaching the network while images are blocked.
 *
 * The height is fixed with internal scrolling rather than measured. Auto
 * sizing an iframe needs a script inside it posting its height out, and a
 * sandbox that allows scripts is not a sandbox.
 */
export interface SandboxedHtmlProps {
  html: string;
  imagesLoaded: boolean;
  title?: string;
}

/**
 * `img-src data:` only while images are blocked: the placeholder pixel is a
 * data URI, so nothing else can be fetched even if a remote `src` slipped
 * past the sanitiser.
 */
function policy(imagesLoaded: boolean): string {
  const images = imagesLoaded ? "https: data:" : "data:";
  return [
    "default-src 'none'",
    `img-src ${images}`,
    "style-src 'unsafe-inline'",
    "font-src data:",
    "form-action 'none'",
    "base-uri 'none'",
    "frame-src 'none'",
    "script-src 'none'",
  ].join("; ");
}

/** Matches the app's type scale, so the iframe does not look pasted in. */
const DOCUMENT_STYLES = `
  :root { color-scheme: light dark; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: Inter, ui-sans-serif, system-ui, sans-serif;
    font-size: 15px;
    line-height: 1.65;
    color: #25232b;
    background: transparent;
    word-break: break-word;
  }
  @media (prefers-color-scheme: dark) {
    body { color: #eceaf2; }
    a { color: #a68fe4; }
  }
  a { color: #8b70d6; }
  img { max-width: 100%; height: auto; }
  table { max-width: 100%; border-collapse: collapse; }
  pre, code { font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 13px; }
  pre { white-space: pre-wrap; overflow-x: auto; }
  blockquote {
    margin: 8px 0; padding-left: 12px;
    border-left: 2px solid rgba(128,128,128,.35);
    color: rgba(128,128,128,1);
  }
`;

export function SandboxedHtml({ html, imagesLoaded, title = "Message" }: SandboxedHtmlProps) {
  const document = useMemo(
    () =>
      [
        "<!doctype html><html><head>",
        '<meta charset="utf-8">',
        `<meta http-equiv="Content-Security-Policy" content="${policy(imagesLoaded)}">`,
        '<meta name="referrer" content="no-referrer">',
        `<style>${DOCUMENT_STYLES}</style>`,
        "</head><body>",
        html,
        "</body></html>",
      ].join(""),
    [html, imagesLoaded],
  );

  return (
    <iframe
      // The empty string is the point: every capability is off.
      sandbox=""
      referrerPolicy="no-referrer"
      srcDoc={document}
      title={title}
      className="h-[60vh] w-full rounded-sm border border-line bg-surface"
    />
  );
}
