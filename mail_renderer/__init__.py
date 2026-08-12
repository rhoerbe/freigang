"""Host-side draft renderer for the freigang mail capability (issue #37).

This package is the ONLY upward path in the mail design. The container never
speaks IMAP: an agent writes a plain-text body plus a small JSON sidecar into
`/workspace/mail-out/`, and this renderer -- running on the host, outside the
container -- validates that input, renders RFC822 with a hard header allowlist,
and IMAP-`APPEND`s the result to the mailbox's `Drafts` folder.

Everything under `mail-out/` is attacker-controlled: it was written by an agent
that has just read untrusted mail. Treat it accordingly.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
