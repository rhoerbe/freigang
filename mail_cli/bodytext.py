"""Decode a message body to plain text.

Prefers text/plain; falls back to text/html stripped to text. Handles
base64 and quoted-printable transfer encodings (via email.message's own
decode=True, which dispatches on Content-Transfer-Encoding) and
multipart/alternative (by walking parts and skipping attachments).
"""

from __future__ import annotations

from email.message import Message
from html.parser import HTMLParser
from typing import ClassVar

TRUNCATION_NOTICE = "\n\n[... body truncated: exceeds size cap ...]"


class _TextExtractingHTMLParser(HTMLParser):
    """Minimal HTML-to-text: strips tags, keeps text, skips style/script."""

    _SKIP_TAGS: ClassVar[set[str]] = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag.lower() in ("br", "p", "div", "tr", "li"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        text = "".join(self._chunks)
        # Collapse runs of blank lines produced by block-tag newlines.
        lines = [line.strip() for line in text.splitlines()]
        collapsed: list[str] = []
        for line in lines:
            if line or (collapsed and collapsed[-1]):
                collapsed.append(line)
        return "\n".join(collapsed).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractingHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _is_attachment(part: Message) -> bool:
    disposition = (part.get_content_disposition() or "").lower()
    return disposition == "attachment"


def _decode_part_text(part: Message) -> str:
    """Decode a leaf MIME part's payload to str.

    get_payload(decode=True) transfer-decodes base64/quoted-printable per
    Content-Transfer-Encoding; we then decode bytes -> str per the part's
    declared charset (defaulting to utf-8, replacing undecodable bytes
    rather than raising on hostile/malformed input).
    """
    raw = part.get_payload(decode=True)
    if raw is None:
        # No transfer-encoding to undo; payload is already a str.
        payload = part.get_payload()
        return payload if isinstance(payload, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _find_first(msg: Message, content_type: str) -> Message | None:
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart() or _is_attachment(part):
                continue
            if part.get_content_type() == content_type:
                return part
        return None
    if msg.get_content_type() == content_type and not _is_attachment(msg):
        return msg
    return None


def extract_body(msg: Message) -> tuple[str, str]:
    """Return (text, source_type) where source_type is 'text/plain' or 'text/html'.

    Prefers text/plain (including the plain branch of a multipart/alternative);
    falls back to text/html rendered to text if no text/plain part exists.
    """
    plain_part = _find_first(msg, "text/plain")
    if plain_part is not None:
        return _decode_part_text(plain_part), "text/plain"

    html_part = _find_first(msg, "text/html")
    if html_part is not None:
        html = _decode_part_text(html_part)
        return html_to_text(html), "text/html"

    return "", "none"


def cap_body(text: str, max_bytes: int) -> str:
    """Truncate `text` to at most `max_bytes` UTF-8 bytes, with a visible marker."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + TRUNCATION_NOTICE
