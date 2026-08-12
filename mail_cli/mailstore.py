"""Read-only access to a Maildir, with stable short ids for messages.

The container only ever reads this Maildir (mounted `ro` in production); this
module never writes into it.
"""

from __future__ import annotations

import hashlib
import mailbox
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

ID_LENGTH = 12


class MailNotFoundError(LookupError):
    """Raised when a requested message id does not exist in the Maildir."""


class FolderNotFoundError(LookupError):
    """Raised when --folder names a folder that is not present."""


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
    folder: str = "INBOX"


def is_maildir(path: Path) -> bool:
    """True if `path` is a Maildir (has the three required subdirectories)."""
    return all((path / sub).is_dir() for sub in ("cur", "new", "tmp"))


def discover_folders(root: Path) -> dict[str, Path]:
    """Map folder name -> Maildir path for everything readable under `root`.

    Three layouts occur in practice:

    - `root` is itself a Maildir (the test fixtures, and any `--maildir` pointed
      straight at one): a single folder named INBOX.
    - `root` holds one Maildir per folder, as mbsync produces with
      `SubFolders Verbatim`: INBOX/, Trash/, "Fronius Support"/ ...
    - nested folders, which mbsync writes as a directory containing further
      Maildirs; those are walked too, and named with `/` separators.

    Ordering puts INBOX first, then the rest alphabetically, so `mail ls`
    leads with the handover folder.
    """
    if is_maildir(root):
        return {"INBOX": root}

    found: dict[str, Path] = {}

    def walk(directory: Path, prefix: str) -> None:
        for child in sorted(directory.iterdir()):
            if not child.is_dir() or child.name in ("cur", "new", "tmp"):
                continue
            name = f"{prefix}{child.name}"
            if is_maildir(child):
                found[name] = child
            walk(child, f"{name}/")

    walk(root, "")
    return dict(sorted(found.items(), key=lambda kv: (kv[0] != "INBOX", kv[0])))


def decode_header_value(raw: str | None, fallback: str) -> str:
    """Decode an RFC 2047 header to text, flattened to a single line.

    Real mail arrives with MIME encoded-words -- `=?utf-8?B?...?=` -- and long
    headers folded across continuation lines. Printed raw they are unreadable
    for the user and, worse, unreadable for the agent, which then reasons about
    base64 instead of a subject. Folding also broke the `mail ls` table.

    Malformed encodings must not take the listing down with them, so anything
    that fails to decode falls back to the raw value.
    """
    if not raw:
        return fallback
    try:
        decoded = str(make_header(decode_header(raw)))
    except (UnicodeDecodeError, LookupError, ValueError):
        decoded = raw
    return " ".join(decoded.split())


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
    """Read-only view over every folder under a synced Maildir root.

    The mount may hold several folders (INBOX, Trash, and whatever the user
    files mail into), so this reads across all of them and labels each message
    with its folder. Ids stay derived from the Message-ID, so a message keeps
    its id if the user moves it between folders.
    """

    def __init__(self, maildir_path: Path, folder: str | None = None):
        self.maildir_path = Path(maildir_path)
        if not self.maildir_path.exists():
            raise FileNotFoundError(f"Maildir not found: {self.maildir_path}")

        self.folders = discover_folders(self.maildir_path)
        if not self.folders:
            raise FileNotFoundError(f"No Maildir folders found under: {self.maildir_path}")
        if folder is not None:
            match = {name: path for name, path in self.folders.items() if name.lower() == folder.lower()}
            if not match:
                known = ", ".join(self.folders) or "(none)"
                raise FolderNotFoundError(f"No folder named {folder!r}. Available: {known}")
            self.folders = match

        # create=False: this process must never create/mutate the Maildir.
        self._mboxes = {
            name: mailbox.Maildir(str(path), factory=None, create=False) for name, path in self.folders.items()
        }

    def _iter_keyed_messages(self):
        for name, mbox in self._mboxes.items():
            for key in mbox.keys():  # noqa: SIM118 -- mailbox.Maildir.__iter__ yields messages, not keys
                yield name, key, mbox.get_message(key)

    def list_entries(self) -> list[MailEntry]:
        """Return summaries for every message, newest first by Date header."""
        entries = []
        for folder, key, msg in self._iter_keyed_messages():
            message_id = msg.get("Message-ID")
            entry_id = compute_id(message_id, key)
            entries.append(
                MailEntry(
                    id=entry_id,
                    key=key,
                    message_id=message_id,
                    date=_format_date(msg),
                    from_addr=decode_header_value(msg.get("From"), "(unknown sender)"),
                    subject=decode_header_value(msg.get("Subject"), "(no subject)"),
                    attachment_count=_count_attachments(msg),
                    folder=folder,
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
        for folder, key, msg in self._iter_keyed_messages():
            message_id = msg.get("Message-ID")
            if compute_id(message_id, key) == entry_id:
                entry = MailEntry(
                    id=entry_id,
                    key=key,
                    message_id=message_id,
                    date=_format_date(msg),
                    from_addr=decode_header_value(msg.get("From"), "(unknown sender)"),
                    subject=decode_header_value(msg.get("Subject"), "(no subject)"),
                    attachment_count=_count_attachments(msg),
                    folder=folder,
                )
                return entry, msg
        raise MailNotFoundError(f"No message with id {entry_id!r} in {self.maildir_path}")
