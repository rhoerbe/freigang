"""Configuration for the mail CLI: paths and caps, overridable for tests.

All paths default to the container mounts (`/mail` read-only, `/workspace`
read-write) but can be overridden via environment variables or CLI flags so
the test suite can point at checked-in fixture Maildirs instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAILDIR = "/mail"
DEFAULT_WORKSPACE = "/workspace"

ENV_MAILDIR = "MAIL_CLI_MAILDIR"
ENV_WORKSPACE = "MAIL_CLI_WORKSPACE"
ENV_ATTACH_MAX_BYTES = "MAIL_CLI_ATTACH_MAX_BYTES"
ENV_BODY_MAX_BYTES = "MAIL_CLI_BODY_MAX_BYTES"

# Attachment size cap: 10 MiB. Deliberately conservative -- attachments are
# meant to be small structured/text artifacts, not bulk data.
DEFAULT_ATTACH_MAX_BYTES = 10 * 1024 * 1024

# Body size cap: 500 KiB of decoded text. Oversize bodies are truncated with
# a visible marker rather than silently emitted in full.
DEFAULT_BODY_MAX_BYTES = 500 * 1024

LEDGER_FILENAME = "mail-ledger.json"
ATTACHMENTS_DIRNAME = "mail-attachments"


def _descend_to_inbox(root: Path) -> Path:
    """Return the Maildir to read: `root/INBOX` when that is the real one.

    mbsync is configured with `Inbox <maildir>/INBOX` and `SubFolders Verbatim`
    (see the agent_mail Ansible role), so the synced tree is

        /mail/INBOX/{cur,new,tmp}
        /mail/Trash/{cur,new,tmp}

    while a bare Maildir is `<root>/{cur,new,tmp}`. Reading `/mail` directly
    therefore fails with "No such file or directory: '/mail/cur'". Descend into
    INBOX when the root is not itself a Maildir and INBOX is one; otherwise
    leave the path alone, so explicit `--maildir` paths and the test fixtures
    keep working unchanged.
    """
    if (root / "cur").is_dir():
        return root
    inbox = root / "INBOX"
    if (inbox / "cur").is_dir():
        return inbox
    return root


@dataclass(frozen=True)
class MailConfig:
    """Resolved configuration for a single CLI invocation."""

    maildir: Path
    workspace: Path
    attach_max_bytes: int = DEFAULT_ATTACH_MAX_BYTES
    body_max_bytes: int = DEFAULT_BODY_MAX_BYTES

    @property
    def ledger_path(self) -> Path:
        return self.workspace / LEDGER_FILENAME

    @property
    def attachments_root(self) -> Path:
        return self.workspace / ATTACHMENTS_DIRNAME

    @classmethod
    def resolve(
        cls,
        maildir: str | Path | None = None,
        workspace: str | Path | None = None,
        attach_max_bytes: int | None = None,
        body_max_bytes: int | None = None,
    ) -> MailConfig:
        """Resolve configuration from explicit args, then env vars, then defaults."""
        resolved_maildir = Path(maildir) if maildir is not None else Path(os.environ.get(ENV_MAILDIR, DEFAULT_MAILDIR))
        resolved_maildir = _descend_to_inbox(resolved_maildir)
        resolved_workspace = (
            Path(workspace) if workspace is not None else Path(os.environ.get(ENV_WORKSPACE, DEFAULT_WORKSPACE))
        )
        resolved_attach_max = (
            attach_max_bytes
            if attach_max_bytes is not None
            else int(os.environ.get(ENV_ATTACH_MAX_BYTES, DEFAULT_ATTACH_MAX_BYTES))
        )
        resolved_body_max = (
            body_max_bytes
            if body_max_bytes is not None
            else int(os.environ.get(ENV_BODY_MAX_BYTES, DEFAULT_BODY_MAX_BYTES))
        )
        return cls(
            maildir=resolved_maildir,
            workspace=resolved_workspace,
            attach_max_bytes=resolved_attach_max,
            body_max_bytes=resolved_body_max,
        )
