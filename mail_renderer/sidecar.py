"""Parsing and validation of the agent-written draft sidecar.

Sidecar format -- one JSON object per draft, written by the agent into
`/workspace/mail-out/<name>.json`, with the body as plain UTF-8 text in a
sibling `<name>.txt`:

    {
      "subject": "Re: heating schedule",
      "in_reply_to": "<1234@example.test>",
      "proposed_recipients": ["someone@example.test"],
      "body_file": "draft-01.txt"
    }

Only `subject` is required. `in_reply_to` must be a message-id that exists in
the synced Maildir. `proposed_recipients` are rendered as visible body text --
they never become headers, so sending still requires the user to type an
address. `body_file` defaults to the sidecar's own stem plus `.txt` and must be
a plain filename inside `mail-out/`.

**Any other key is dropped, not merged.** In particular `to`, `cc`, `bcc`,
`reply-to`, `from`, `sender`, `return-path` and a nested `headers` object have
no effect whatsoever: the renderer's header allowlist is closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from mail_renderer.config import RendererConfig
from mail_renderer.errors import SidecarError
from mail_renderer.guards import (
    MAX_PROPOSED_RECIPIENTS,
    sanitize_for_body,
    validate_message_id,
    validate_subject,
)
from mail_renderer.safeio import UnsafeReadError, read_bytes_nofollow

# The complete set of keys that have any effect. Everything else is dropped.
RECOGNIZED_KEYS = frozenset({"subject", "in_reply_to", "proposed_recipients", "body_file"})


@dataclass(frozen=True)
class Sidecar:
    """A validated draft request. Nothing here is trusted beyond its type."""

    path: Path
    subject: str
    body_path: Path
    in_reply_to: str | None = None
    proposed_recipients: tuple[str, ...] = ()
    dropped_keys: tuple[str, ...] = field(default=())

    @property
    def name(self) -> str:
        return self.path.name


def _read_json_object(path: Path, max_bytes: int) -> dict:
    # Opened once, with O_NOFOLLOW; the symlink, regular-file and size checks
    # all come from that descriptor, so there is no check-then-read window for
    # the agent to swap the file in (see mail_renderer.safeio).
    try:
        raw = read_bytes_nofollow(path, max_bytes, f"sidecar {path.name}")
    except UnsafeReadError as exc:
        raise SidecarError(str(exc)) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise SidecarError(f"sidecar is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SidecarError(f"sidecar is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SidecarError(f"sidecar must be a JSON object, got {type(payload).__name__}")
    return payload


def _resolve_body_path(config: RendererConfig, sidecar_path: Path, raw_name: object) -> Path:
    if raw_name is None:
        name = f"{sidecar_path.stem}.txt"
    elif isinstance(raw_name, str):
        name = raw_name
    else:
        raise SidecarError(f"body_file must be a string, got {type(raw_name).__name__}")

    # A plain basename only: no separators, no traversal, no dotfiles.
    if name != Path(name).name or name in {"", ".", ".."} or name.startswith("."):
        raise SidecarError(f"body_file must be a plain filename inside mail-out/, got {name!r}")

    candidate = config.mail_out / name
    # Symlinks are the interesting attack here: the agent can create one inside
    # the workspace pointing at, say, the IMAP credential, and have the
    # renderer post its contents to Drafts.
    if candidate.is_symlink():
        raise SidecarError(f"body file {name!r} is a symlink; refusing to follow it")
    if not candidate.is_file():
        raise SidecarError(f"body file {name!r} does not exist in mail-out/")
    if candidate.resolve().parent != config.mail_out.resolve():
        raise SidecarError(f"body file {name!r} resolves outside mail-out/")

    size = candidate.stat().st_size
    if size > config.max_body_bytes:
        raise SidecarError(f"body is {size} bytes, over the {config.max_body_bytes}-byte cap")
    return candidate


def _validate_recipients(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list):
        raise SidecarError(f"proposed_recipients must be a string or a list, got {type(raw).__name__}")
    if len(values) > MAX_PROPOSED_RECIPIENTS:
        raise SidecarError(f"proposed_recipients has {len(values)} entries, over the {MAX_PROPOSED_RECIPIENTS} cap")
    recipients = tuple(sanitize_for_body(value) for value in values)
    return tuple(recipient for recipient in recipients if recipient)


def load_sidecar(path: Path, config: RendererConfig) -> Sidecar:
    """Parse and validate one sidecar. Raises `SidecarError` on anything odd."""
    payload = _read_json_object(path, config.max_sidecar_bytes)

    if "subject" not in payload:
        raise SidecarError("sidecar has no subject")
    subject = validate_subject(payload["subject"])

    raw_in_reply_to = payload.get("in_reply_to")
    in_reply_to = None if raw_in_reply_to is None else validate_message_id("in_reply_to", raw_in_reply_to)

    recipients = _validate_recipients(payload.get("proposed_recipients"))
    body_path = _resolve_body_path(config, path, payload.get("body_file"))
    dropped = tuple(sorted(key for key in payload if key not in RECOGNIZED_KEYS))

    return Sidecar(
        path=path,
        subject=subject,
        body_path=body_path,
        in_reply_to=in_reply_to,
        proposed_recipients=recipients,
        dropped_keys=dropped,
    )
