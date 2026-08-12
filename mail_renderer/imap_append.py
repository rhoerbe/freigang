"""IMAP `APPEND` to the Drafts folder -- the only upward operation that exists.

The renderer deliberately implements nothing else: no SMTP, no `STORE`, no
`EXPUNGE`, no upward flag sync. The credential is read from a file outside the
container-writable tree, at append time, and is never written anywhere else.
"""

from __future__ import annotations

import imaplib
import re
import ssl
import time
from pathlib import Path
from types import TracebackType
from typing import Self

from mail_renderer.config import RendererConfig
from mail_renderer.errors import ConfigError


class AppendError(Exception):
    """The APPEND did not succeed. The draft stays where it is, recoverable."""


def read_credential(path: Path) -> str:
    """Read the IMAP password, refusing anything with loose permissions."""
    if path.is_symlink():
        raise ConfigError(f"credential {path} is a symlink; refusing to follow it")
    if not path.is_file():
        raise ConfigError(f"credential {path} does not exist")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ConfigError(f"credential {path} has mode {mode:04o}; expected 0600")
    password = path.read_text(encoding="utf-8").strip()
    if not password:
        raise ConfigError(f"credential {path} is empty")
    return password


def resolve_folder(folder: str, prefix: str) -> str:
    """Qualify `folder` with the server's personal namespace prefix.

    Hetzner's Dovecot reports a personal namespace of `INBOX.` with `.` as the
    delimiter, so every mailbox lives under it and a bare `Drafts` is rejected:

        APPEND to Drafts returned NO: Client tried to access nonexistent
        namespace. (Mailbox name should probably be prefixed with: INBOX.)

    Servers without a prefix report an empty one and the name passes through, so
    the configured `drafts_folder` stays portable rather than hard-coding a
    server's layout. An already-qualified name is left alone.
    """
    if not prefix or folder == prefix.rstrip(".") or folder.startswith(prefix):
        return folder
    return f"{prefix}{folder}"


def _quote(folder: str) -> str:
    """Quote a mailbox name for IMAP commands (names may contain spaces)."""
    escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class ImapAppender:
    """Opens one IMAP session per run and APPENDs each rendered draft to it."""

    def __init__(self, config: RendererConfig):
        self._config = config
        self._imap: imaplib.IMAP4_SSL | None = None
        self._prefix = ""
        self._ensured: set[str] = set()

    def __enter__(self) -> Self:
        password = read_credential(self._config.imap_password_file)
        try:
            self._imap = imaplib.IMAP4_SSL(
                host=self._config.imap_host,
                port=self._config.imap_port,
                ssl_context=ssl.create_default_context(),
            )
            self._imap.login(self._config.imap_user, password)
            self._prefix = self._personal_prefix()
        except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
            raise AppendError(f"IMAP login to {self._config.imap_host} failed: {exc}") from exc
        finally:
            del password
        return self

    def _personal_prefix(self) -> str:
        """Read the personal namespace prefix, or "" if the server has none."""
        try:
            status, data = self._imap.namespace()
        except (imaplib.IMAP4.error, AttributeError):
            return ""
        if status != "OK" or not data:
            return ""
        # (("INBOX." ".")) NIL NIL  ->  INBOX.
        match = re.search(rb'\(\("([^"]*)"\s+"([^"]*)"\)\)', data[0] or b"")
        return match.group(1).decode() if match else ""

    def _ensure_folder(self, folder: str) -> None:
        """Create (and subscribe) the folder when the server does not have it.

        A fresh mailbox has no Drafts folder at all, so the first APPEND would
        fail even once the namespace prefix is right. Creating it is the one
        mailbox write this design makes beyond APPEND, and it is required for
        the drafts to have anywhere to land.
        """
        if folder in self._ensured:
            return
        try:
            # imaplib sends `LIST <directory> <pattern>` verbatim; the directory
            # must be the literal two-character string `""`, not an empty Python
            # string, or Dovecot answers BAD "Invalid pattern".
            status, data = self._imap.list('""', _quote(folder))
            exists = status == "OK" and any(row for row in (data or []) if row)
            if not exists:
                create_status, create_data = self._imap.create(_quote(folder))
                if create_status != "OK":
                    raise AppendError(f"could not create {folder}: {create_data!r}")
                self._imap.subscribe(_quote(folder))
        except imaplib.IMAP4.error as exc:
            raise AppendError(f"could not prepare {folder}: {exc}") from exc
        self._ensured.add(folder)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
        finally:
            self._imap = None

    def append(self, folder: str, raw: bytes) -> None:
        if self._imap is None:
            raise AppendError("IMAP session is not open")
        folder = resolve_folder(folder, self._prefix)
        self._ensure_folder(folder)
        try:
            status, data = self._imap.append(
                folder,
                r"(\Draft)",
                imaplib.Time2Internaldate(time.time()),
                raw,
            )
        except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
            raise AppendError(f"APPEND to {folder} failed: {exc}") from exc
        if status != "OK":
            raise AppendError(f"APPEND to {folder} returned {status}: {data!r}")
