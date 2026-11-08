"""HTML to readable text, with the stdlib parser and no dependency.

A marketing email is ~200 KB of markup around ~2 KB of text (gap B2), so this
runs before anything measures a message's size, let alone pays for tokens on
it.

It is deliberately small. Block elements become newlines, ``<br>`` becomes
one, scripts and styles are dropped, entities are unescaped. It is not a
renderer and does not try to be: the body a person reads is fetched from
Gmail on demand and sanitised at the edge (gap E6).
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

__all__ = ["html_to_text"]

_DROP = {"script", "style", "head", "title", "meta", "link", "noscript"}
_BLOCK = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "section",
    "article",
    "header",
    "footer",
    "table",
    "ul",
    "ol",
    "pre",
}
_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING = re.compile(r"[ \t]+\n")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppress = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP:
            self._suppress += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP and self._suppress:
            self._suppress -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._suppress and data.strip():
            self.parts.append(data)

    def error(self, message: str) -> None:  # pragma: no cover - py3.10 ABC
        return None


def html_to_text(html: str | None) -> str | None:
    """Readable text, or None when there was nothing to read."""
    if not html:
        return None

    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Fall back to stripping tags crudely rather than losing the body.
        parser.parts = [re.sub(r"<[^>]+>", " ", html)]

    text = unescape("".join(parser.parts))
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _TRAILING.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return text or None
