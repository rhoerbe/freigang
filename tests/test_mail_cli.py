"""End-to-end CLI smoke tests: `mail ls` / `mail show` / `mail attach` argv wiring."""

from __future__ import annotations

from pathlib import Path

from mail_cli.cli import main
from mail_cli.config import MailConfig
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


def test_maildir_root_with_inbox_subfolder_is_resolved(tmp_path: Path):
    """The synced layout is /mail/INBOX/{cur,new,tmp}, not /mail/{cur,new,tmp}.

    mbsync is configured with `Inbox <maildir>/INBOX` and `SubFolders Verbatim`,
    so pointing at the mount root must still find the mail. MailConfig keeps the
    root as given; MailStore discovers the folders beneath it.
    """
    root = tmp_path / "mail"
    for folder in ("INBOX", "Trash"):
        for sub in ("cur", "new", "tmp"):
            (root / folder / sub).mkdir(parents=True)
    (root / "INBOX" / "cur" / "1700000000.x:2,S").write_bytes(
        b"From: someone@example.test\nSubject: synced\nMessage-ID: <synced-1@example.test>\n\nbody\n"
    )

    config = MailConfig.resolve(maildir=root, workspace=tmp_path / "ws")
    assert config.maildir == root
    store = MailStore(config.maildir)
    assert list(store.folders) == ["INBOX", "Trash"]
    assert len(store.list_entries()) == 1


def test_flat_maildir_is_treated_as_inbox(tmp_path: Path):
    """A bare Maildir stays supported -- the fixtures and --maildir rely on it."""
    root = tmp_path / "flat"
    for sub in ("cur", "new", "tmp"):
        (root / sub).mkdir(parents=True)
    assert MailConfig.resolve(maildir=root, workspace=tmp_path / "ws").maildir == root
    assert list(MailStore(root).folders) == ["INBOX"]


def _make_message(path: Path, msg_id: str, subject: str) -> None:
    path.write_bytes(
        f"From: someone@example.test\nSubject: {subject}\nMessage-ID: {msg_id}\n\nbody\n".encode()
    )


def _make_folder(root: Path, name: str) -> Path:
    folder = root / name
    for sub in ("cur", "new", "tmp"):
        (folder / sub).mkdir(parents=True)
    return folder


def test_messages_in_subfolders_are_listed_with_their_folder(tmp_path: Path, capsys):
    """Mail filed into a folder must be visible, labelled with that folder.

    mbsync writes one Maildir per folder under the mount root, so reading only
    <root>/INBOX made foldered mail invisible with no error -- the user's mail
    was on disk and `mail ls` said nothing was there.
    """
    root = tmp_path / "mail"
    _make_message(_make_folder(root, "INBOX") / "cur" / "1.a:2,S", "<in-1@example.test>", "in inbox")
    _make_message(_make_folder(root, "Fronius Support") / "cur" / "2.b:2,S", "<fs-1@example.test>", "in folder")
    _make_folder(root, "Trash")

    store = MailStore(root)
    assert list(store.folders) == ["INBOX", "Fronius Support", "Trash"]  # INBOX first
    assert {e.folder for e in store.list_entries()} == {"INBOX", "Fronius Support"}

    assert main(["ls", "--maildir", str(root), "--workspace", str(tmp_path / "ws")]) == 0
    out = capsys.readouterr().out
    assert "FOLDER" in out
    assert "Fronius Support" in out and "in folder" in out


def test_folder_filter_restricts_and_reports_unknown_names(tmp_path: Path, capsys):
    root = tmp_path / "mail"
    _make_message(_make_folder(root, "INBOX") / "cur" / "1.a:2,S", "<in-1@example.test>", "in inbox")
    _make_message(_make_folder(root, "Fronius Support") / "cur" / "2.b:2,S", "<fs-1@example.test>", "in folder")

    entries = MailStore(root, folder="fronius support").list_entries()  # case-insensitive
    assert [e.subject for e in entries] == ["in folder"]

    assert main(["ls", "--folder", "Nope", "--maildir", str(root), "--workspace", str(tmp_path / "ws")]) == 1
    assert "No folder named 'Nope'" in capsys.readouterr().err


def test_nested_folders_are_walked(tmp_path: Path):
    root = tmp_path / "mail"
    _make_folder(root, "INBOX")
    _make_message(_make_folder(root, "Projects/Solar") / "cur" / "3.c:2,S", "<n-1@example.test>", "nested")
    assert "Projects/Solar" in MailStore(root).folders


def test_message_id_is_stable_across_folders(tmp_path: Path):
    """Ids come from the Message-ID, so filing mail elsewhere must not renumber it."""
    a, b = tmp_path / "a", tmp_path / "b"
    _make_message(_make_folder(a, "INBOX") / "cur" / "1.x:2,S", "<same@example.test>", "s")
    _make_message(_make_folder(b, "Archive") / "cur" / "1.y:2,S", "<same@example.test>", "s")
    assert MailStore(a).list_entries()[0].id == MailStore(b).list_entries()[0].id
