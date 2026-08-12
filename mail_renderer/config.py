"""Configuration for the host-side draft renderer.

Every address, path and cap is a variable -- nothing about a specific mailbox is
hard-coded into the rendering logic. Defaults describe the first consumer
(`ha_agent`); the Ansible role passes explicit values via the environment, and
the CLI accepts overrides so the test suite can point at temporary directories.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from mail_renderer.errors import ConfigError

DEFAULT_MAIL_OUT = "/home/ha_agent/workspace/mail-out"
DEFAULT_MAILDIR = "/home/ha_agent/mail"

# The IMAP credential lives in a sibling of the workspace, deliberately never
# mounted into the container (see the agent_mail Ansible role, issue #37).
DEFAULT_IMAP_PASSWORD_FILE = "/home/ha_agent/.mailsync/imap_password"

DEFAULT_DRAFTS_FOLDER = "Drafts"
DEFAULT_IMAP_PORT = 993

# Caps: a runaway agent loop must not be able to fill the mailbox.
DEFAULT_MAX_DRAFTS_PER_RUN = 20
DEFAULT_MAX_BODY_BYTES = 256 * 1024
DEFAULT_MAX_SIDECAR_BYTES = 64 * 1024

POSTED_DIRNAME = "posted"
FAILED_DIRNAME = "failed"

ENV_PREFIX = "MAIL_RENDERER_"

# Deliberately strict: a configured address is operator-supplied, so there is no
# reason for it to be anything other than a bare addr-spec.
_ADDRESS_RE = re.compile(r"^[^\s<>@,;:\"\\]+@[A-Za-z0-9._-]+\.[A-Za-z0-9-]+$")


def _env(name: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    return value if value else None


def _env_int(name: str) -> int | None:
    value = _env(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name} is not an integer: {value!r}") from exc


def _is_within(candidate: Path, root: Path) -> bool:
    """True if `candidate` lies inside `root` (lexically, after resolution)."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class RendererConfig:
    """Resolved configuration for a single renderer run."""

    mail_out: Path
    maildir: Path
    from_addr: str
    to_addr: str
    imap_host: str
    imap_user: str
    imap_password_file: Path = Path(DEFAULT_IMAP_PASSWORD_FILE)
    imap_port: int = DEFAULT_IMAP_PORT
    drafts_folder: str = DEFAULT_DRAFTS_FOLDER
    max_drafts_per_run: int = DEFAULT_MAX_DRAFTS_PER_RUN
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    max_sidecar_bytes: int = DEFAULT_MAX_SIDECAR_BYTES

    @property
    def posted_dir(self) -> Path:
        return self.mail_out / POSTED_DIRNAME

    @property
    def failed_dir(self) -> Path:
        return self.mail_out / FAILED_DIRNAME

    @property
    def workspace(self) -> Path:
        """The container-writable tree. Nothing secret may live inside it."""
        return self.mail_out.parent

    @classmethod
    def resolve(cls, **overrides: object) -> RendererConfig:
        """Resolve from explicit overrides, then environment, then defaults."""
        values: dict[str, object] = {
            "mail_out": Path(_env("MAIL_OUT") or DEFAULT_MAIL_OUT),
            "maildir": Path(_env("MAILDIR") or DEFAULT_MAILDIR),
            "from_addr": _env("FROM") or "",
            "to_addr": _env("TO") or "",
            "imap_host": _env("IMAP_HOST") or "",
            "imap_user": _env("IMAP_USER") or "",
            "imap_password_file": Path(_env("IMAP_PASSWORD_FILE") or DEFAULT_IMAP_PASSWORD_FILE),
            "imap_port": _env_int("IMAP_PORT") or DEFAULT_IMAP_PORT,
            "drafts_folder": _env("DRAFTS_FOLDER") or DEFAULT_DRAFTS_FOLDER,
            "max_drafts_per_run": _env_int("MAX_DRAFTS") or DEFAULT_MAX_DRAFTS_PER_RUN,
            "max_body_bytes": _env_int("MAX_BODY_BYTES") or DEFAULT_MAX_BODY_BYTES,
            "max_sidecar_bytes": _env_int("MAX_SIDECAR_BYTES") or DEFAULT_MAX_SIDECAR_BYTES,
        }
        for key, value in overrides.items():
            if value is None:
                continue
            if key not in values:
                raise ConfigError(f"Unknown configuration key: {key}")
            values[key] = Path(value) if isinstance(values[key], Path) else value  # type: ignore[arg-type]
        return cls(**values)  # type: ignore[arg-type]

    def validate(self) -> None:
        """Refuse to run on an unsafe or incomplete configuration."""
        for label, address in (("from_addr", self.from_addr), ("to_addr", self.to_addr)):
            if not address:
                raise ConfigError(f"{label} is not configured")
            if not _ADDRESS_RE.match(address):
                raise ConfigError(f"{label} is not a bare address: {address!r}")
        if not self.imap_host:
            raise ConfigError("imap_host is not configured")
        if not self.imap_user:
            raise ConfigError("imap_user is not configured")
        if not self.drafts_folder or any(ch in self.drafts_folder for ch in "\r\n\"{"):
            raise ConfigError(f"drafts_folder is not a plain folder name: {self.drafts_folder!r}")
        for label, cap in (
            ("max_drafts_per_run", self.max_drafts_per_run),
            ("max_body_bytes", self.max_body_bytes),
            ("max_sidecar_bytes", self.max_sidecar_bytes),
        ):
            if cap <= 0:
                raise ConfigError(f"{label} must be positive, got {cap}")

        # The credential must never be reachable from the container-writable
        # tree. This is the guarantee the whole design rests on: the agent may
        # not read, copy or reference it.
        for root_label, root in (("workspace", self.workspace), ("mail-out", self.mail_out)):
            if _is_within(self.imap_password_file, root):
                raise ConfigError(
                    f"imap_password_file {self.imap_password_file} lies inside the {root_label} tree "
                    f"({root}); the IMAP credential must never be reachable from the container"
                )
        if _is_within(self.maildir, self.workspace):
            raise ConfigError(
                f"maildir {self.maildir} lies inside the workspace tree ({self.workspace}); "
                "the synced mail must stay outside the container-writable tree"
            )
