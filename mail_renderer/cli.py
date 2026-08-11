"""Command-line entry point: `python3 -m mail_renderer` (host-side only).

Runs one drain pass. Intended to be driven by the `mail-renderer` systemd user
timer installed by the `agent_mail` Ansible role; it is safe to run by hand.

Exit codes:
  0  the run completed (drafts may have been rejected -- see failed/)
  1  the IMAP side failed, or the configuration was refused; drafts are intact
"""

from __future__ import annotations

import argparse
import logging
import sys

from mail_renderer.config import RendererConfig
from mail_renderer.drain import drain
from mail_renderer.errors import ConfigError
from mail_renderer.imap_append import AppendError, ImapAppender

log = logging.getLogger("mail_renderer.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mail-renderer",
        description="Render agent-proposed drafts from mail-out/ and APPEND them to IMAP Drafts.",
    )
    parser.add_argument("--mail-out", help="Directory the agent writes drafts into")
    parser.add_argument("--maildir", help="Synced Maildir used to validate In-Reply-To")
    parser.add_argument("--from-addr", dest="from_addr", help="Hard-coded From address")
    parser.add_argument("--to-addr", dest="to_addr", help="Hard-coded To address (the mailbox owner)")
    parser.add_argument("--imap-host", dest="imap_host")
    parser.add_argument("--imap-port", dest="imap_port", type=int)
    parser.add_argument("--imap-user", dest="imap_user")
    parser.add_argument("--imap-password-file", dest="imap_password_file")
    parser.add_argument("--drafts-folder", dest="drafts_folder")
    parser.add_argument("--max-drafts", dest="max_drafts_per_run", type=int)
    parser.add_argument("--max-body-bytes", dest="max_body_bytes", type=int)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    overrides = {key: value for key, value in vars(args).items() if key != "verbose" and value is not None}
    try:
        config = RendererConfig.resolve(**overrides)
        config.validate()
    except ConfigError as exc:
        log.error("configuration refused: %s", exc)
        return 1

    if not config.mail_out.is_dir():
        log.info("nothing to do: %s does not exist", config.mail_out)
        return 0

    try:
        with ImapAppender(config) as appender:
            report = drain(config, appender)
    except (AppendError, ConfigError) as exc:
        log.error("IMAP unavailable, drafts left untouched: %s", exc)
        return 1

    log.info("posted=%d failed=%d deferred=%d", len(report.posted), len(report.failed), len(report.deferred))
    for entry in report.append_errors:
        log.error("append error: %s", entry)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
