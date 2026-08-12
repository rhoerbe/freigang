"""Read-only access to a Maildir, with stable short ids for messages.

The container only ever reads this Maildir (mounted `ro` in production); this
module never writes into it.
"""

from __future__ import annotations

import hashlib
import mailbox
from dataclasses import dataclass
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

ID_LENGTH = 12


class MailNotFoundError(LookupError):
    """Raised when a requested message id does not exist in the Maildir."""


def compute_id(message_id_header: str | None, fallback_key: str) -> str:
    """Derive a stable short id for a message.

    Prefers the RFC 5322 Message-ID header (stable across re-syncs); falls
    back to the Maildir key (filename) for messages missing one.
    """
    basis = message_id_header if message_id_header else f"maildir-key:{fallback_key}"
    digest = hashlib.sha256(basis.encode("utf-8", errors="surrogateescape")).hexdigest()
    return digest[:ID_LENGTH]


@dataclass(frozen=True)
class MailEntry:
    """Summary of one message, as shown by `mail ls`."""

    id: str
    key: str
    message_id: str | None
    date: str
    from_addr: str
    subject: str
    attachment_count: int


def _count_attachments(msg: Message) -> int:
    count = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition == "attachment" or (filename and disposition != "inline"):
            count += 1
    return count


def _format_date(msg: Message) -> str:
    raw = msg.get("Date")
    if not raw:
        return "(no date)"
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return raw
    if dt is None:
        return raw
    return dt.strftime("%Y-%m-%d %H:%M")


class MailStore:
    """Read-only wrapper around a Maildir, indexed by stable short id."""

    def __init__(self, maildir_path: Path):
        self.maildir_path = Path(maildir_path)
        if not self.maildir_path.exists():
            raise FileNotFoundError(f"Maildir not found: {self.maildir_path}")
        # create=False: this process must never create/mutate the Maildir.
        self._mbox = mailbox.Maildir(str(self.maildir_path), factory=None, create=False)

    def _iter_keyed_messages(self):
        for key in self._mbox.keys():  # noqa: SIM118 -- mailbox.Maildir.__iter__ yields messages, not keys
            yield key, self._mbox.get_message(key)

    def list_entries(self) -> list[MailEntry]:
        """Return summaries for every message, newest first by Date header."""
        entries = []
        for key, msg in self._iter_keyed_messages():
            message_id = msg.get("Message-ID")
            entry_id = compute_id(message_id, key)
            entries.append(
                MailEntry(
                    id=entry_id,
                    key=key,
                    message_id=message_id,
                    date=_format_date(msg),
                    from_addr=msg.get("From", "(unknown sender)"),
                    subject=msg.get("Subject", "(no subject)"),
                    attachment_count=_count_attachments(msg),
                )
            )
        entries.sort(key=lambda e: e.date, reverse=True)
        return entries

    def get_message(self, entry_id: str) -> tuple[MailEntry, Message]:
        """Look up a message by its short id.

        Raises MailNotFoundError if no message has that id. A ledger entry
        never affects this lookup or the result of list_entries() -- the
        processed marker is purely advisory and applied by the caller.
        """
        for key, msg in self._iter_keyed_messages():
            message_id = msg.get("Message-ID")
            if compute_id(message_id, key) == entry_id:
                entry = MailEntry(
                    id=entry_id,
                    key=key,
                    message_id=message_id,
                    date=_format_date(msg),
                    from_addr=msg.get("From", "(unknown sender)"),
                    subject=msg.get("Subject", "(no subject)"),
                    attachment_count=_count_attachments(msg),
                )
                return entry, msg
        raise MailNotFoundError(f"No message with id {entry_id!r} in {self.maildir_path}")
