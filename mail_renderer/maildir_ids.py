"""Collect the Message-IDs present in the synced Maildir.

Used only to decide whether an agent-proposed `In-Reply-To` names a real
message. Reading is bounded: header blocks only, with caps on both the number
of files visited and the bytes read per file, because the Maildir is filled
from an untrusted source (whatever the user dragged into the mailbox).
"""

from __future__ import annotations

from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path

from mail_renderer.guards import MESSAGE_ID_RE, normalize_message_id

DEFAULT_MAX_FILES = 50_000
DEFAULT_MAX_HEADER_BYTES = 64 * 1024


def _message_ids_in(path: Path, max_header_bytes: int) -> set[str]:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(max_header_bytes)
    except OSError:
        return set()

    for separator in (b"\r\n\r\n", b"\n\n"):
        index = chunk.find(separator)
        if index != -1:
            chunk = chunk[:index]
            break

    headers = BytesParser(policy=compat32).parsebytes(chunk, headersonly=True)
    found = set()
    for raw in headers.get_all("Message-ID", []):
        candidate = normalize_message_id(" ".join(str(raw).split()))
        if MESSAGE_ID_RE.match(candidate):
            found.add(candidate)
    return found


def collect_message_ids(
    maildir: Path,
    max_files: int = DEFAULT_MAX_FILES,
    max_header_bytes: int = DEFAULT_MAX_HEADER_BYTES,
) -> set[str]:
    """Return every well-formed Message-ID found under `maildir`'s cur/ and new/."""
    ids: set[str] = set()
    if not maildir.is_dir():
        return ids

    visited = 0
    for subdir in ("cur", "new"):
        for path in sorted(maildir.glob(f"**/{subdir}/*")):
            if path.is_symlink() or not path.is_file():
                continue
            visited += 1
            if visited > max_files:
                return ids
            ids |= _message_ids_in(path, max_header_bytes)
    return ids
