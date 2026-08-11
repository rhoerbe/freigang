"""Drain `mail-out/`: validate, render, APPEND, and move the sidecars.

Drain semantics, per issue #37:

- success  -> sidecar and body are MOVED to `mail-out/posted/`, never deleted,
              so a mistake is always recoverable and auditable.
- malformed -> sidecar and body are moved to `mail-out/failed/` with a
              `<name>.error` file beside them, so a missing draft is
              diagnosable rather than mysterious.
- APPEND failure -> nothing is moved. The draft stays exactly where the agent
              left it and the run stops, so a mail server outage does not burn
              through the whole queue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from mail_renderer.config import RendererConfig
from mail_renderer.errors import ConfigError, DraftError
from mail_renderer.imap_append import AppendError
from mail_renderer.maildir_ids import collect_message_ids
from mail_renderer.render import build_message, render_bytes
from mail_renderer.sidecar import load_sidecar

log = logging.getLogger(__name__)


class Appender(Protocol):
    """Minimal upward interface: append raw RFC822 bytes to one folder."""

    def append(self, folder: str, raw: bytes) -> None: ...


@dataclass
class DrainReport:
    posted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    append_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.append_errors


def _ensure_subdir(parent: Path, name: str) -> Path:
    path = parent / name
    if path.is_symlink():
        raise ConfigError(f"{path} is a symlink; refusing to drain into it")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_destination(directory: Path, name: str) -> Path:
    candidate = directory / name
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = directory / f"{name}.{index}"
        index += 1
    return candidate


def _move(path: Path, directory: Path) -> Path:
    destination = _unique_destination(directory, path.name)
    path.rename(destination)
    return destination


def _move_draft(sidecar_path: Path, body_path: Path | None, directory: Path) -> None:
    """Move the sidecar plus its body (default-named or explicit) together."""
    candidates = [body_path] if body_path is not None else []
    default_body = sidecar_path.with_suffix(".txt")
    if default_body not in candidates:
        candidates.append(default_body)
    for candidate in candidates:
        if candidate is not None and (candidate.exists() or candidate.is_symlink()):
            _move(candidate, directory)
    _move(sidecar_path, directory)


def _record_failure(sidecar_path: Path, body_path: Path | None, failed_dir: Path, reason: str) -> None:
    name = sidecar_path.name
    _move_draft(sidecar_path, body_path, failed_dir)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    error_file = _unique_destination(failed_dir, f"{name}.error")
    error_file.write_text(f"{stamp} {reason}\n", encoding="utf-8")


class _KnownIds:
    """Lazily scan the Maildir: only drafts that thread need the ID set."""

    def __init__(self, maildir: Path):
        self._maildir = maildir
        self._ids: set[str] | None = None

    def get(self) -> set[str]:
        if self._ids is None:
            self._ids = collect_message_ids(self._maildir)
        return self._ids


def pending_sidecars(config: RendererConfig) -> list[Path]:
    """Top-level `*.json` files in mail-out/, oldest name first. Stable order."""
    return sorted(path for path in config.mail_out.glob("*.json") if path.is_file() or path.is_symlink())


def drain(config: RendererConfig, appender: Appender, known_ids: set[str] | None = None) -> DrainReport:
    """Process up to `max_drafts_per_run` sidecars. Never raises on bad input."""
    report = DrainReport()
    posted_dir = _ensure_subdir(config.mail_out, "posted")
    failed_dir = _ensure_subdir(config.mail_out, "failed")
    ids = _KnownIds(config.maildir) if known_ids is None else None

    sidecars = pending_sidecars(config)
    batch = sidecars[: config.max_drafts_per_run]
    report.deferred.extend(path.name for path in sidecars[config.max_drafts_per_run :])

    for index, sidecar_path in enumerate(batch):
        try:
            sidecar = load_sidecar(sidecar_path, config)
            body_text = sidecar.body_path.read_text(encoding="utf-8", errors="replace")
            if sidecar.dropped_keys:
                log.warning(
                    "%s: dropped non-allowlisted sidecar keys %s", sidecar_path.name, list(sidecar.dropped_keys)
                )
            message = build_message(config, sidecar, body_text, ids.get() if ids is not None else known_ids or set())
            raw = render_bytes(message)
        except DraftError as exc:
            log.warning("%s: rejected -- %s", sidecar_path.name, exc)
            _record_failure(sidecar_path, None, failed_dir, str(exc))
            report.failed.append(sidecar_path.name)
            continue
        except OSError as exc:
            log.warning("%s: unreadable -- %s", sidecar_path.name, exc)
            _record_failure(sidecar_path, None, failed_dir, f"unreadable: {exc}")
            report.failed.append(sidecar_path.name)
            continue

        try:
            appender.append(config.drafts_folder, raw)
        except AppendError as exc:
            # Leave everything in place: the agent's work must survive an outage.
            log.error("%s: APPEND failed -- %s", sidecar_path.name, exc)
            report.append_errors.append(f"{sidecar_path.name}: {exc}")
            report.deferred.extend(path.name for path in batch[index:])
            return report

        _move_draft(sidecar_path, sidecar.body_path, posted_dir)
        report.posted.append(sidecar_path.name)

    return report
