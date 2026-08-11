"""`mail` CLI: ls / show / attach against a read-only Maildir.

See GitHub issue #37 for the full design and rationale. The container never
speaks IMAP -- this tool only ever reads a Maildir synced in by a host-side
job, and writes only into /workspace (ledger, extracted attachments).
"""

from __future__ import annotations

import argparse
import sys

from mail_cli import bodytext
from mail_cli.attachments import (
    AttachmentNotFoundError,
    AttachmentRejectedError,
    extract_attachment,
    list_attachments,
)
from mail_cli.config import MailConfig
from mail_cli.ledger import Ledger
from mail_cli.mailstore import MailNotFoundError, MailStore
from mail_cli.provenance import wrap_untrusted


def _add_common_path_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--maildir", default=None, help="Path to the Maildir (default: $MAIL_CLI_MAILDIR or /mail)")
    parser.add_argument(
        "--workspace", default=None, help="Path to the workspace dir (default: $MAIL_CLI_WORKSPACE or /workspace)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mail", description="Read a synced, read-only Maildir.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ls_parser = subparsers.add_parser("ls", help="List messages")
    _add_common_path_args(ls_parser)

    show_parser = subparsers.add_parser("show", help="Show a decoded message body")
    show_parser.add_argument("id", help="Message id, as shown by `mail ls`")
    show_parser.add_argument(
        "--no-mark-processed",
        action="store_true",
        help="Do not record this message in the advisory processed-ledger",
    )
    _add_common_path_args(show_parser)

    attach_parser = subparsers.add_parser("attach", help="Extract one attachment")
    attach_parser.add_argument("id", help="Message id, as shown by `mail ls`")
    attach_parser.add_argument("n", type=int, help="1-based attachment number, as shown by `mail show`")
    _add_common_path_args(attach_parser)

    return parser


def _config_from_args(args: argparse.Namespace) -> MailConfig:
    return MailConfig.resolve(maildir=args.maildir, workspace=args.workspace)


def cmd_ls(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = MailStore(config.maildir)
    ledger = Ledger(config.ledger_path)
    entries = store.list_entries()

    if not entries:
        print("(no messages)")
        return 0

    header = f"{'ID':12}  {'DATE':16}  {'PROC':4}  {'ATT':3}  {'FROM':30}  SUBJECT"
    print(header)
    for entry in entries:
        marker = "x" if ledger.is_processed(entry.id) else " "
        from_addr = entry.from_addr[:30]
        print(f"{entry.id:12}  {entry.date:16}  {marker:^4}  {entry.attachment_count:3}  {from_addr:30}  {entry.subject}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = MailStore(config.maildir)
    ledger = Ledger(config.ledger_path)

    try:
        entry, msg = store.get_message(args.id)
    except MailNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    body, source_type = bodytext.extract_body(msg)
    body = bodytext.cap_body(body, config.body_max_bytes)
    attachments = list_attachments(msg)

    print(f"Date: {entry.date}")
    print(f"From: {entry.from_addr}")
    print(f"Subject: {entry.subject}")
    print(f"Message-ID: {entry.message_id or '(none)'}")
    print(f"Attachments: {len(attachments)}")
    for ref in attachments:
        print(f"  [{ref.index}] {ref.declared_filename or '(unnamed)'} ({ref.content_type})")
    print(f"Body-source: {source_type}")
    print()
    print(wrap_untrusted(body))

    if not args.no_mark_processed:
        ledger.mark_processed(entry.id)

    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    store = MailStore(config.maildir)

    try:
        entry, msg = store.get_message(args.id)
    except MailNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        dest = extract_attachment(
            msg,
            args.n,
            msg_short_id=entry.id,
            attachments_root=config.attachments_root,
            max_bytes=config.attach_max_bytes,
        )
    except AttachmentNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except AttachmentRejectedError as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return 2

    print(f"extracted: {dest}")
    return 0


COMMANDS = {
    "ls": cmd_ls,
    "show": cmd_show,
    "attach": cmd_attach,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
