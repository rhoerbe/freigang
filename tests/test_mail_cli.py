"""End-to-end CLI smoke tests: `mail ls` / `mail show` / `mail attach` argv wiring."""

from __future__ import annotations

from pathlib import Path

from mail_cli.cli import main
from mail_cli.mailstore import MailStore


def test_ls_lists_all_fixture_messages(security_maildir: Path, workspace: Path, capsys):
    rc = main(["ls", "--maildir", str(security_maildir), "--workspace", str(workspace)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Weekly status" in out
    assert "Run this tool" in out
    assert "Please review the attached settings" in out


def test_ls_on_empty_maildir_reports_no_messages(tmp_path: Path, workspace: Path, capsys):
    empty_maildir = tmp_path / "empty-mail"
    for sub in ("cur", "new", "tmp"):
        (empty_maildir / sub).mkdir(parents=True)

    rc = main(["ls", "--maildir", str(empty_maildir), "--workspace", str(workspace)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no messages" in out


def test_show_unknown_id_reports_error_and_nonzero_exit(security_maildir: Path, workspace: Path, capsys):
    rc = main(["show", "0" * 12, "--maildir", str(security_maildir), "--workspace", str(workspace)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "error" in err.lower()


def test_attach_end_to_end_extracts_allowlisted_attachment(
    security_maildir: Path, workspace: Path, find_id_by_subject, capsys
):
    store = MailStore(security_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "Large log file")

    rc = main(["attach", msg_id, "1", "--maildir", str(security_maildir), "--workspace", str(workspace)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "extracted:" in out

    extracted_files = list((workspace / "mail-attachments" / msg_id).glob("*"))
    assert len(extracted_files) == 1
    assert extracted_files[0].name == "big.log"


def test_attach_rejected_attachment_exits_nonzero_and_writes_nothing(
    security_maildir: Path, workspace: Path, find_id_by_subject, capsys
):
    store = MailStore(security_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "Run this tool")

    rc = main(["attach", msg_id, "1", "--maildir", str(security_maildir), "--workspace", str(workspace)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "rejected" in err.lower()
    assert not (workspace / "mail-attachments").exists() or not any(
        (workspace / "mail-attachments").rglob("*")
    )
