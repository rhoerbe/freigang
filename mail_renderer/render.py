"""RFC822 rendering with a closed header allowlist.

This module is the privilege boundary. Two rules make it safe:

1. The message is built with `email.message.EmailMessage`; header values are
   never hand-formatted with f-strings or concatenation, so a CRLF in an
   agent-supplied field cannot become a header separator. Fields are guarded
   before they are assigned (see `mail_renderer.guards`) and the finished
   message is re-parsed from its serialized bytes and re-checked.
2. Only `From`, `To`, `Subject`, `Date` and `In-Reply-To` may exist.
   `From`/`To` are configuration, not agent input; `Date` is generated here.
   The single agent-controlled headers are `Subject` and `In-Reply-To`, and the
   latter must name a message that is actually in the synced Maildir.

Recipients the agent proposes are rendered as visible body text, so sending a
draft requires the user to consciously type an address.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate

from mail_renderer.config import RendererConfig
from mail_renderer.errors import RenderError
from mail_renderer.guards import normalize_message_id, validate_message_id, validate_subject
from mail_renderer.sidecar import Sidecar

# Non-negotiable. Anything the agent proposes beyond these is dropped.
ALLOWED_HEADERS = ("From", "To", "Subject", "Date", "In-Reply-To")

# Structural headers the MIME serializer adds itself; not agent input.
STRUCTURAL_HEADERS = frozenset({"mime-version", "content-type", "content-transfer-encoding"})

PROPOSED_RECIPIENTS_BANNER = (
    "-- recipients proposed by the agent (NOT addressed) ------------------\n"
    "The agent suggested sending this to the addresses below. They are shown\n"
    "here as plain text only and are deliberately not in any header: to send,\n"
    "type the address into the To: field yourself."
)

DRAFT_FOOTER = "-- draft composed by the freigang mail agent; nothing was sent ---------"


def compose_body(sidecar: Sidecar, body_text: str) -> str:
    """Body text plus, if any, the proposed recipients as visible lines."""
    sections = [body_text.rstrip("\n")]
    if sidecar.proposed_recipients:
        sections.append("")
        sections.append(PROPOSED_RECIPIENTS_BANNER)
        sections.extend(f"    {recipient}" for recipient in sidecar.proposed_recipients)
    sections.append("")
    sections.append(DRAFT_FOOTER)
    return "\n".join(sections) + "\n"


def assert_only_allowed_headers(message: EmailMessage) -> None:
    """Fail closed if any header outside the allowlist made it into the message."""
    allowed = {header.lower() for header in ALLOWED_HEADERS} | STRUCTURAL_HEADERS
    present = {name.lower() for name, _ in message.items()}
    unexpected = present - allowed
    if unexpected:
        raise RenderError(f"rendered message carries non-allowlisted headers: {sorted(unexpected)}")


def build_message(
    config: RendererConfig,
    sidecar: Sidecar,
    body_text: str,
    known_message_ids: set[str],
) -> EmailMessage:
    """Render one validated sidecar into an `EmailMessage`.

    `known_message_ids` comes from the synced Maildir; an `In-Reply-To` that is
    not in it is refused, so the field can only ever be a threading reference
    and never a free-form channel for smuggling data out of the container.
    """
    message = EmailMessage()

    # Configuration, never agent input.
    message["From"] = config.from_addr
    message["To"] = config.to_addr
    message["Date"] = formatdate(localtime=True)

    # Re-validate rather than trusting the sidecar object: this function is the
    # last gate before the bytes exist, and it is cheap.
    message["Subject"] = validate_subject(sidecar.subject)

    if sidecar.in_reply_to is not None:
        in_reply_to = validate_message_id("in_reply_to", sidecar.in_reply_to)
        known = {normalize_message_id(value) for value in known_message_ids}
        if normalize_message_id(in_reply_to) not in known:
            raise RenderError(
                f"in_reply_to {in_reply_to} is not a Message-ID present in the synced Maildir; "
                "refusing to use it as a threading reference"
            )
        message["In-Reply-To"] = in_reply_to

    message.set_content(compose_body(sidecar, body_text), subtype="plain", charset="utf-8", cte="quoted-printable")

    assert_only_allowed_headers(message)
    return message


def render_bytes(message: EmailMessage) -> bytes:
    """Serialize with CRLF line endings, then re-parse and re-check the headers.

    The re-parse is deliberate belt-and-braces: it is the check that would catch
    a header being smuggled in through folding rather than through assignment.
    """
    raw = message.as_bytes(policy=policy.SMTP)
    reparsed = BytesParser(policy=policy.SMTP).parsebytes(raw)
    allowed = {header.lower() for header in ALLOWED_HEADERS} | STRUCTURAL_HEADERS
    unexpected = {name.lower() for name, _ in reparsed.items()} - allowed
    if unexpected:
        raise RenderError(f"serialized message carries non-allowlisted headers: {sorted(unexpected)}")
    return raw
