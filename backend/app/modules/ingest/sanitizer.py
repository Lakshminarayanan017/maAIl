"""Make sender-controlled HTML safe to put on screen.

Gap D3. Rendering email is an XSS and tracking hole, and the three parts of
it need three different answers:

**Scripts and handlers** are removed by `nh3` (the Rust `ammonia` library)
against a strict allowlist. This is deliberately not a hand-rolled regex: an
HTML sanitiser is a parser-differential problem, and the list of ways to
smuggle a script past a naive filter is longer than this file.

**Remote images** are rewritten to nothing unless the reader asks for them.
A single-pixel image is how a sender learns when, where and how often a
message was opened; loading it by default answers that question without
being asked.

**Link text that disagrees with its href** is flagged rather than rewritten.
`<a href="http://evil.test">paypal.com</a>` is the oldest trick there is,
and the honest response is to show the reader both.

The output goes into a sandboxed iframe with its own CSP, so even a miss
here has no origin to act in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

import nh3

__all__ = ["SanitisedBody", "sanitize_email_html"]

#: Structure and emphasis. No forms, no iframes, no objects, no media.
ALLOWED_TAGS: set[str] = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "li",
    "ol",
    "p",
    "pre",
    "q",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

#: `style` is allowed on the containers email actually uses for layout, and
#: nowhere else. It is filtered again below for `url()` and `expression()`.
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan", "align", "style"},
    "th": {"colspan", "rowspan", "align", "style"},
    "table": {"width", "align", "style"},
    "div": {"style"},
    "span": {"style"},
    "p": {"style"},
    "blockquote": {"style", "type"},
    "pre": {"style"},
}

#: Everything else, `javascript:` and `data:` included, is dropped.
ALLOWED_SCHEMES: set[str] = {"http", "https", "mailto", "tel", "cid"}

#: A transparent 1x1 GIF. Keeps the layout from collapsing where a blocked
#: image was, without fetching anything.
BLOCKED_PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

#: Styles that can still fetch or execute despite the tag allowlist.
_DANGEROUS_CSS = re.compile(
    r"(?:url\s*\(|expression\s*\(|@import|behavior\s*:|-moz-binding)", re.IGNORECASE
)

_STYLE_ATTR = re.compile(r"style\s*=\s*([\"'])(.*?)", re.IGNORECASE | re.DOTALL)

#: Anchor text that is itself trying to look like a destination.
_LOOKS_LIKE_HOST = re.compile(
    r"^\s*(?:https?://)?((?:[\w-]+\.)+[a-z]{2,})(?:[/?#]\S*)?\s*$", re.IGNORECASE
)


@dataclass
class LinkWarning:
    """Anchor text claims one destination; the href goes somewhere else."""

    text: str
    href: str
    claimed_host: str
    actual_host: str


@dataclass
class SanitisedBody:
    html: str
    #: How many remote images were withheld. Drives the "load images"
    #: control, and is zero when there is nothing to ask about.
    blocked_images: int = 0
    images_loaded: bool = False
    link_warnings: list[LinkWarning] = field(default_factory=list)
    #: Set when the original had nothing but markup.
    empty: bool = False


def sanitize_email_html(html: str | None, *, load_images: bool = False) -> SanitisedBody:
    """Clean HTML for display inside a sandboxed iframe."""
    if not html or not html.strip():
        return SanitisedBody(html="", empty=True)

    warnings = _find_link_mismatches(html)

    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={tag: set(attrs) for tag, attrs in ALLOWED_ATTRIBUTES.items()},
        url_schemes=ALLOWED_SCHEMES,
        strip_comments=True,
        link_rel="noopener noreferrer nofollow",
    )

    cleaned, blocked = _handle_images(cleaned, load_images=load_images)
    cleaned = _strip_dangerous_css(cleaned)

    return SanitisedBody(
        html=cleaned,
        blocked_images=blocked,
        images_loaded=load_images,
        link_warnings=warnings,
        empty=not cleaned.strip(),
    )


def _handle_images(html: str, *, load_images: bool) -> tuple[str, int]:
    """Replace remote image sources until the reader opts in.

    ``cid:`` images are inline attachments that travelled with the message,
    so they leak nothing and are left alone — though phase 3 does not serve
    them yet, which makes them a broken image rather than a tracker.
    """
    blocked = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal blocked
        source = match.group(2)
        scheme = urlparse(source).scheme.lower()
        if scheme in ("", "cid", "data"):
            return match.group(0)
        if load_images:
            return match.group(0)
        blocked += 1
        return f'{match.group(1)}"{BLOCKED_PIXEL}" data-blocked-src="{_escape(source)}"'

    pattern = re.compile(r'(\bsrc\s*=\s*)["\']([^"\']*)["\']', re.IGNORECASE)
    return pattern.sub(replace, html), blocked


def _strip_dangerous_css(html: str) -> str:
    """Drop any `style` attribute that could fetch or execute.

    Coarse on purpose. A style attribute is a convenience for layout; one
    containing `url(` is a background image request, which is the same
    tracking pixel wearing a different hat.
    """

    def replace(match: re.Match[str]) -> str:
        return "" if _DANGEROUS_CSS.search(match.group(2)) else match.group(0)

    return re.sub(
        r'(\bstyle\s*=\s*)(["\'])(.*?)\2',
        lambda m: replace(re.match(r'(\bstyle\s*=\s*)["\'](.*)["\']', m.group(0), re.DOTALL) or m),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, list[str]]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._flush()
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def _flush(self) -> None:
        if self._href is not None:
            self.links.append((self._href, self._text))
        self._href = None
        self._text = []

    def error(self, message: str) -> None:  # pragma: no cover - py3.10 ABC
        return None


def _find_link_mismatches(html: str) -> list[LinkWarning]:
    """Anchors whose visible text names a different host than the href.

    Only flags text that is *trying* to look like a destination. "Click
    here" pointing at example.test is a link; "paypal.com" pointing at
    evil.test is a lie, and only the second is worth a badge.
    """
    collector = _LinkCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:
        return []

    warnings: list[LinkWarning] = []
    for href, parts in collector.links:
        text = "".join(parts).strip()
        if not text or not href:
            continue
        claim = _LOOKS_LIKE_HOST.match(text)
        if not claim:
            continue
        actual = urlparse(href).hostname or ""
        claimed = claim.group(1).lower()
        if not actual:
            continue
        if _registrable(actual) != _registrable(claimed):
            warnings.append(
                LinkWarning(
                    text=text[:200], href=href[:500], claimed_host=claimed, actual_host=actual
                )
            )
    return warnings


def _registrable(host: str) -> str:
    """The last two labels. Good enough to tell paypal.com from evil.test.

    Not a public-suffix list: that would be a dependency and a download for
    a warning badge. The failure mode is a missed warning on a `.co.uk`
    subdomain, never a false accusation of a legitimate link.
    """
    parts = host.lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
