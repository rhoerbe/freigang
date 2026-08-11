"""Input guards shared by the sidecar parser and the renderer.

Every value that can end up in -- or near -- a header goes through here first.
`EmailMessage` also refuses multi-line header values, but its check is
`len(value.splitlines()) > 1`, which lets a *trailing* CRLF through; these
guards close that gap and are applied before the message is ever built.
"""

from __future__ import annotations

import re

from mail_renderer.errors import SidecarError

# C0 controls (including CR, LF and TAB), DEL, and the Unicode line/paragraph
# separators. None of these has any business in a header-bound field.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")

# A single RFC 5322 msg-id, and nothing else: one pair of angle brackets, one
# at-sign, no whitespace, no trailing second id.
MESSAGE_ID_RE = re.compile(r"^<[^\s<>@]+@[^\s<>@]+>$")

MAX_SUBJECT_CHARS = 512
MAX_MESSAGE_ID_CHARS = 998
MAX_PROPOSED_RECIPIENTS = 10
MAX_RECIPIENT_DISPLAY_CHARS = 320


def ensure_header_safe(label: str, value: object, max_chars: int) -> str:
    """Return `value` as a header-safe string, or raise `SidecarError`."""
    if not isinstance(value, str):
        raise SidecarError(f"{label} must be a string, got {type(value).__name__}")
    if len(value) > max_chars:
        raise SidecarError(f"{label} is longer than the {max_chars}-character cap ({len(value)})")
    match = CONTROL_CHARS_RE.search(value)
    if match:
        raise SidecarError(
            f"{label} contains the control character {match.group(0)!r}; "
            "header injection attempt or corrupt input -- refusing"
        )
    return value


def validate_subject(value: object) -> str:
    subject = ensure_header_safe("subject", value, MAX_SUBJECT_CHARS)
    if not subject.strip():
        raise SidecarError("subject is empty")
    return subject


def validate_message_id(label: str, value: object) -> str:
    """Validate a single message-id. Lists, multiple ids and CRLF are refused."""
    message_id = ensure_header_safe(label, value, MAX_MESSAGE_ID_CHARS).strip()
    if not MESSAGE_ID_RE.match(message_id):
        raise SidecarError(f"{label} is not a single well-formed message-id: {message_id!r}")
    return message_id


def normalize_message_id(value: str) -> str:
    """Normalize for comparison: strip whitespace, ensure angle brackets."""
    message_id = value.strip()
    if message_id and not message_id.startswith("<"):
        message_id = f"<{message_id}"
    if message_id and not message_id.endswith(">"):
        message_id = f"{message_id}>"
    return message_id


def sanitize_for_body(value: object) -> str:
    """Flatten an agent-proposed string for safe display inside the body.

    Body text cannot inject headers, but a proposed recipient containing CRLF
    could still forge the renderer's own banner lines, so it is flattened.
    """
    if not isinstance(value, str):
        raise SidecarError(f"proposed recipient must be a string, got {type(value).__name__}")
    flattened = CONTROL_CHARS_RE.sub(" ", value).strip()
    if len(flattened) > MAX_RECIPIENT_DISPLAY_CHARS:
        flattened = flattened[:MAX_RECIPIENT_DISPLAY_CHARS] + " [truncated]"
    return flattened
