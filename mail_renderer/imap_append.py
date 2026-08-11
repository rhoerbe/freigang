"""IMAP `APPEND` to the Drafts folder -- the only upward operation that exists.

The renderer deliberately implements nothing else: no SMTP, no `STORE`, no
`EXPUNGE`, no upward flag sync. The credential is read from a file outside the
container-writable tree, at append time, and is never written anywhere else.
"""

from __future__ import annotations

import imaplib
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


class ImapAppender:
    """Opens one IMAP session per run and APPENDs each rendered draft to it."""

    def __init__(self, config: RendererConfig):
        self._config = config
        self._imap: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> Self:
        password = read_credential(self._config.imap_password_file)
        try:
            self._imap = imaplib.IMAP4_SSL(
                host=self._config.imap_host,
                port=self._config.imap_port,
                ssl_context=ssl.create_default_context(),
            )
            self._imap.login(self._config.imap_user, password)
        except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
            raise AppendError(f"IMAP login to {self._config.imap_host} failed: {exc}") from exc
        finally:
            del password
        return self

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
