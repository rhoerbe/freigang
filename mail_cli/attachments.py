"""Explicit, allowlisted, on-demand attachment extraction.

Security properties (see GitHub issue #37):

- Extraction happens only when the caller explicitly asks for one numbered
  attachment (`mail attach <id> <n>`) -- never automatically from `mail show`.
- MIME/extension allowlist: text/*, application/json, YAML, CSV, .log.
  Anything off the allowlist is REJECTED outright -- there is deliberately
  no --force escape hatch. Do not add one.
- A size cap is enforced before any bytes are written.
- The destination filename is computed by this module from the message id
  and attachment index, sanitized to a basename -- NEVER taken verbatim from
  the MIME `filename` header. This defeats
  `filename="../../.claude/settings.json"` style path traversal: the
  attacker-controlled name can only ever contribute a basename component
  used as a hint, written strictly inside the per-message quarantine dir.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
from pathlib import Path, PurePosixPath

ALLOWED_MIME_PREFIXES = ("text/",)

ALLOWED_MIME_TYPES = {
    "application/json",
    "application/x-yaml",
    "application/yaml",
    "text/yaml",
    "text/x-yaml",
    "text/csv",
}

# Extensions accepted even when the declared Content-Type is generic/wrong
# (e.g. application/octet-stream), because mail clients frequently mislabel
# plain structured-text attachments this way.
ALLOWED_EXTENSIONS = {".txt", ".log", ".csv", ".json", ".yaml", ".yml", ".md"}

DEFAULT_ATTACHMENT_BASENAME = "attachment"


class AttachmentRejectedError(ValueError):
    """Raised when an attachment is off-allowlist or exceeds the size cap."""


class AttachmentNotFoundError(LookupError):
    """Raised when the requested attachment index does not exist."""


@dataclass(frozen=True)
class AttachmentRef:
    """A located, not-yet-extracted attachment part."""

    index: int
    part: Message
    declared_filename: str | None
    content_type: str


def list_attachments(msg: Message) -> list[AttachmentRef]:
    """Enumerate attachment parts in a stable, 1-based order."""
    refs = []
    index = 1
    for part in msg.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition == "attachment" or (filename and disposition != "inline"):
            refs.append(
                AttachmentRef(
                    index=index,
                    part=part,
                    declared_filename=filename,
                    content_type=part.get_content_type(),
                )
            )
            index += 1
    return refs


def _sanitize_basename(declared_filename: str | None, fallback: str) -> str:
    """Reduce an attacker-controlled filename to a safe basename only.

    Strips any directory components (POSIX or Windows separators, `..`
    segments) by taking PurePosixPath(...).name of the name after also
    stripping backslash-separated components. Falls back to a computed
    name if nothing usable remains.
    """
    if not declared_filename:
        return fallback
    # Normalize Windows-style separators too, then take the final path
    # component only -- this is what defeats `../../x` traversal: the
    # traversal prefix is discarded, not sanitized-in-place.
    normalized = declared_filename.replace("\\", "/")
    name = PurePosixPath(normalized).name
    name = name.strip()
    if name in ("", ".", ".."):
        return fallback
    # Guard against leading dot-only or empty-after-strip names.
    if name.startswith("."):
        name = f"attachment_{name}"
    return name


def _is_allowed(content_type: str, filename: str) -> bool:
    content_type = (content_type or "").lower()
    if any(content_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        return True
    if content_type in ALLOWED_MIME_TYPES:
        return True
    extension = PurePosixPath(filename).suffix.lower()
    return extension in ALLOWED_EXTENSIONS


def get_attachment(msg: Message, index: int) -> AttachmentRef:
    refs = list_attachments(msg)
    for ref in refs:
        if ref.index == index:
            return ref
    raise AttachmentNotFoundError(f"No attachment #{index} (message has {len(refs)} attachment(s))")


def extract_attachment(
    msg: Message,
    index: int,
    msg_short_id: str,
    attachments_root: Path,
    max_bytes: int,
) -> Path:
    """Extract attachment `index` from `msg` to a quarantine dir; return its path.

    Raises AttachmentNotFoundError / AttachmentRejectedError instead of
    writing anything when the attachment is missing, off-allowlist, or
    oversize.
    """
    ref = get_attachment(msg, index)

    fallback_name = f"{DEFAULT_ATTACHMENT_BASENAME}-{index}"
    safe_name = _sanitize_basename(ref.declared_filename, fallback_name)

    if not _is_allowed(ref.content_type, safe_name):
        raise AttachmentRejectedError(
            f"Attachment #{index} ({ref.content_type!r}, filename {safe_name!r}) is not on the "
            "allowlist (text/*, application/json, YAML, CSV, .log) and was not extracted."
        )

    payload = ref.part.get_payload(decode=True)
    if payload is None:
        payload = (ref.part.get_payload() or "").encode("utf-8", errors="replace")

    if len(payload) > max_bytes:
        raise AttachmentRejectedError(
            f"Attachment #{index} is {len(payload)} bytes, exceeding the {max_bytes}-byte cap; not extracted."
        )

    dest_dir = attachments_root / msg_short_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name

    # Belt-and-suspenders: safe_name is guaranteed separator-free by
    # _sanitize_basename (it is a PurePosixPath(...).name), so dest_path's
    # parent must always be dest_dir itself. Refuse to write otherwise.
    if dest_path.parent.resolve() != dest_dir.resolve():
        raise AttachmentRejectedError("Refusing to write attachment outside the quarantine directory.")

    dest_path.write_bytes(payload)
    return dest_path
