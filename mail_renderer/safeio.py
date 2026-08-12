"""Race-free reads of agent-written files.

Every file this renderer consumes from `mail-out/` is written by the agent
inside the container, which owns that directory. Validating a path and *then*
opening it by name leaves a window in which the agent can swap the file for a
symlink between the two operations -- so a check-then-read that proves "this is
a regular file inside mail-out/" proves nothing about the bytes that are
actually read a moment later.

The concrete attack that window reopens is the one the path guards exist to
close: point the body file at `/home/ha_agent/.mailsync/imap_password` and have
the *host* renderer post the IMAP credential into Drafts.

So the file is opened exactly once, with `O_NOFOLLOW` (the open itself fails if
the final component is a symlink), and everything afterwards -- the regular-file
check, the size cap, the content -- comes from that one file descriptor. There
is no second name lookup to race.

Swapping in a different *regular* file remains possible and is deliberately not
defended against: the agent may write whatever it likes into `mail-out/`
already, so that is not an escalation.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from mail_renderer.errors import DraftError


class UnsafeReadError(DraftError):
    """The file could not be read under the guarantees this module provides.

    A `DraftError` so `drain` routes it to `failed/` with an error file, like
    any other rejected input, rather than aborting the run.
    """


def read_bytes_nofollow(path: Path, max_bytes: int, label: str) -> bytes:
    """Read `path` without ever following a symlink, capped at `max_bytes`.

    Raises `UnsafeReadError` if the final path component is a symlink, if the
    opened file is not a regular file, or if it exceeds the cap.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise UnsafeReadError(f"{label} is a symlink; refusing to follow it") from exc
        if exc.errno == errno.ENOENT:
            raise UnsafeReadError(f"{label} does not exist") from exc
        raise UnsafeReadError(f"{label} could not be opened: {exc}") from exc

    with os.fdopen(fd, "rb", closefd=True) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UnsafeReadError(f"{label} is not a regular file")
        if info.st_size > max_bytes:
            raise UnsafeReadError(f"{label} is {info.st_size} bytes, over the {max_bytes}-byte cap")
        # Read one byte past the cap so a file that grew between fstat and read
        # is still rejected rather than silently truncated.
        data = handle.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise UnsafeReadError(f"{label} is over the {max_bytes}-byte cap")
    return data
