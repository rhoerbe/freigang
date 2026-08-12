"""Behaviour tests for the host-side draft renderer (issue #37, phase 4).

The security properties live in `test_mail_renderer_security.py`; this file
covers the ordinary path: a well-formed sidecar becomes a well-formed draft,
drained files land in `posted/`, configuration resolves from the environment,
and the credential reader refuses a loosely-permissioned file.
"""

from __future__ import annotations

import json
from email import message_from_bytes, policy
import imaplib
from pathlib import Path

import pytest

from mail_renderer.config import DEFAULT_DRAFTS_FOLDER, RendererConfig
from mail_renderer.drain import drain, pending_sidecars
from mail_renderer.errors import ConfigError
from mail_renderer.imap_append import read_credential
from mail_renderer.maildir_ids import collect_message_ids
from mail_renderer.render import DRAFT_FOOTER, build_message, compose_body, render_bytes
from mail_renderer.sidecar import load_sidecar

FROM_ADDR = "ha_agent@example.test"
TO_ADDR = "owner@example.test"
KNOWN_ID = "<known-thread-1@example.test>"


class FakeAppender:
    def __init__(self):
        self.appended: list[tuple[str, bytes]] = []

    def append(self, folder: str, raw: bytes) -> None:
        self.appended.append((folder, raw))


@pytest.fixture
def synced_maildir(tmp_path: Path) -> Path:
    maildir = tmp_path / "mail"
    cur = maildir / "INBOX" / "cur"
    cur.mkdir(parents=True)
    (maildir / "INBOX" / "new").mkdir()
    (cur / "1700000000.abc:2,S").write_bytes(
        b"From: someone@example.test\r\nSubject: alert\r\nMessage-ID: " + KNOWN_ID.encode() + b"\r\n\r\nbody\r\n"
    )
    return maildir


@pytest.fixture
def mail_out(tmp_path: Path) -> Path:
    out = tmp_path / "workspace" / "mail-out"
    out.mkdir(parents=True)
    return out


@pytest.fixture
def config(mail_out: Path, synced_maildir: Path, tmp_path: Path) -> RendererConfig:
    return RendererConfig(
        mail_out=mail_out,
        maildir=synced_maildir,
        from_addr=FROM_ADDR,
        to_addr=TO_ADDR,
        imap_host="imap.example.test",
        imap_user="ha_agent@example.test",
        imap_password_file=tmp_path / "credentials" / "imap_password",
        max_body_bytes=8192,
    )


def write_draft(mail_out: Path, name: str, sidecar: dict, body: str = "hello") -> Path:
    path = mail_out / f"{name}.json"
    path.write_text(json.dumps(sidecar), encoding="utf-8")
    (mail_out / f"{name}.txt").write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_well_formed_draft_renders_the_expected_headers(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "ok", {"subject": "Heizung: Zeitplan", "in_reply_to": KNOWN_ID}, body="Servus")
    sidecar = load_sidecar(path, config)
    message = build_message(config, sidecar, "Servus", {KNOWN_ID})

    assert message["From"] == FROM_ADDR
    assert message["To"] == TO_ADDR
    assert message["Subject"] == "Heizung: Zeitplan"
    assert message["In-Reply-To"] == KNOWN_ID
    assert message["Date"]


def test_rendered_bytes_use_crlf_and_survive_a_reparse(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "crlf", {"subject": "Grüße"}, body="Zeile eins\nZeile zwei")
    message = build_message(config, load_sidecar(path, config), "Zeile eins\nZeile zwei", set())
    raw = render_bytes(message)

    assert b"\r\n" in raw
    # Non-ASCII is RFC 2047-encoded on the wire and decodes back cleanly.
    assert "Grüße".encode() not in raw
    reparsed = message_from_bytes(raw, policy=policy.default)
    assert reparsed["Subject"] == "Grüße"
    assert "Zeile zwei" in reparsed.get_content()


def test_body_carries_the_draft_footer(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "footer", {"subject": "s"}, body="text")
    message = build_message(config, load_sidecar(path, config), "text", set())
    assert DRAFT_FOOTER in message.get_content()


def test_compose_body_lists_proposed_recipients_after_the_text(config: RendererConfig, mail_out: Path):
    path = write_draft(
        mail_out,
        "props",
        {"subject": "s", "proposed_recipients": ["a@example.test", "b@example.test"]},
        body="the answer",
    )
    body = compose_body(load_sidecar(path, config), "the answer")
    assert body.index("the answer") < body.index("a@example.test") < body.index("b@example.test")


def test_unrecognized_sidecar_keys_are_reported_as_dropped(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "extra", {"subject": "s", "bcc": "x@y.test", "priority": "high"})
    sidecar = load_sidecar(path, config)
    assert sidecar.dropped_keys == ("bcc", "priority")


def test_explicit_body_file_is_honoured(config: RendererConfig, mail_out: Path):
    (mail_out / "prose.txt").write_text("from the explicit body file", encoding="utf-8")
    path = mail_out / "explicit.json"
    path.write_text(json.dumps({"subject": "s", "body_file": "prose.txt"}), encoding="utf-8")
    sidecar = load_sidecar(path, config)
    assert sidecar.body_path.name == "prose.txt"


# ---------------------------------------------------------------------------
# Drain
# ---------------------------------------------------------------------------


def test_successful_drain_moves_sidecar_and_body_to_posted(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "good", {"subject": "s"}, body="text")
    appender = FakeAppender()
    report = drain(config, appender)

    assert report.posted == ["good.json"]
    assert report.ok
    assert (config.posted_dir / "good.json").exists()
    assert (config.posted_dir / "good.txt").read_text(encoding="utf-8") == "text"
    assert not (mail_out / "good.json").exists()
    folder, raw = appender.appended[0]
    assert folder == DEFAULT_DRAFTS_FOLDER
    assert message_from_bytes(raw)["Subject"] == "s"


def test_drain_on_an_empty_directory_is_a_no_op(config: RendererConfig):
    report = drain(config, FakeAppender())
    assert (report.posted, report.failed, report.deferred) == ([], [], [])
    assert report.ok


def test_drain_processes_sidecars_in_stable_name_order(config: RendererConfig, mail_out: Path):
    for name in ["c", "a", "b"]:
        write_draft(mail_out, name, {"subject": name})
    assert [path.name for path in pending_sidecars(config)] == ["a.json", "b.json", "c.json"]
    appender = FakeAppender()
    drain(config, appender)
    assert [message_from_bytes(raw)["Subject"] for _, raw in appender.appended] == ["a", "b", "c"]


def test_posted_collision_does_not_overwrite_an_earlier_draft(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "dup", {"subject": "first"}, body="first body")
    drain(config, FakeAppender())
    write_draft(mail_out, "dup", {"subject": "second"}, body="second body")
    drain(config, FakeAppender())

    assert (config.posted_dir / "dup.json").exists()
    assert (config.posted_dir / "dup.json.1").exists()
    bodies = {path.read_text(encoding="utf-8") for path in config.posted_dir.glob("dup.txt*")}
    assert bodies == {"first body", "second body"}


# ---------------------------------------------------------------------------
# Maildir scan
# ---------------------------------------------------------------------------


def test_collect_message_ids_finds_ids_in_cur_and_new(synced_maildir: Path):
    (synced_maildir / "INBOX" / "new" / "1700000001.def").write_bytes(
        b"Subject: newer\nMessage-ID: <second@example.test>\n\nbody\n"
    )
    assert collect_message_ids(synced_maildir) == {KNOWN_ID, "<second@example.test>"}


def test_collect_message_ids_on_a_missing_maildir_returns_empty(tmp_path: Path):
    assert collect_message_ids(tmp_path / "absent") == set()


def test_collect_message_ids_ignores_body_text_that_looks_like_a_header(synced_maildir: Path):
    (synced_maildir / "INBOX" / "new" / "1700000002.ghi").write_bytes(
        b"Subject: sneaky\n\nMessage-ID: <in-the-body@evil.tld>\n"
    )
    assert "<in-the-body@evil.tld>" not in collect_message_ids(synced_maildir)


# ---------------------------------------------------------------------------
# Configuration and credential handling
# ---------------------------------------------------------------------------


def test_config_resolves_from_the_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAIL_RENDERER_MAIL_OUT", str(tmp_path / "ws" / "mail-out"))
    monkeypatch.setenv("MAIL_RENDERER_MAILDIR", str(tmp_path / "mail"))
    monkeypatch.setenv("MAIL_RENDERER_FROM", FROM_ADDR)
    monkeypatch.setenv("MAIL_RENDERER_TO", TO_ADDR)
    monkeypatch.setenv("MAIL_RENDERER_IMAP_HOST", "imap.example.test")
    monkeypatch.setenv("MAIL_RENDERER_IMAP_USER", "ha_agent@example.test")
    monkeypatch.setenv("MAIL_RENDERER_IMAP_PASSWORD_FILE", str(tmp_path / ".mailsync" / "imap_password"))
    monkeypatch.setenv("MAIL_RENDERER_MAX_DRAFTS", "3")

    config = RendererConfig.resolve()
    config.validate()
    assert config.from_addr == FROM_ADDR
    assert config.max_drafts_per_run == 3
    assert config.drafts_folder == DEFAULT_DRAFTS_FOLDER


def test_explicit_overrides_beat_the_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MAIL_RENDERER_TO", "env@example.test")
    config = RendererConfig.resolve(to_addr="explicit@example.test", mail_out=str(tmp_path))
    assert config.to_addr == "explicit@example.test"
    assert config.mail_out == tmp_path


def test_config_rejects_a_non_address_from(config: RendererConfig, tmp_path: Path):
    bad = RendererConfig(
        mail_out=config.mail_out,
        maildir=config.maildir,
        from_addr="ha_agent (at) example.test",
        to_addr=TO_ADDR,
        imap_host="imap.example.test",
        imap_user="ha_agent@example.test",
        imap_password_file=tmp_path / "credentials" / "imap_password",
    )
    with pytest.raises(ConfigError):
        bad.validate()


def test_credential_with_loose_permissions_is_refused(tmp_path: Path):
    secret = tmp_path / "imap_password"
    secret.write_text("hunter2\n", encoding="utf-8")
    secret.chmod(0o644)
    with pytest.raises(ConfigError):
        read_credential(secret)


def test_credential_with_0600_is_read_and_stripped(tmp_path: Path):
    secret = tmp_path / "imap_password"
    secret.write_text("hunter2\n", encoding="utf-8")
    secret.chmod(0o600)
    assert read_credential(secret) == "hunter2"


def test_missing_credential_is_refused(tmp_path: Path):
    with pytest.raises(ConfigError):
        read_credential(tmp_path / "absent")


class FakeImap:
    """Minimal IMAP double for namespace/list/create/append behaviour."""

    def __init__(self, prefix=b'(("INBOX." ".")) NIL NIL', existing=()):
        self.prefix_payload = prefix
        self.existing = set(existing)
        self.created: list[str] = []
        self.subscribed: list[str] = []
        self.appended: list[tuple[str, bytes]] = []

    def namespace(self):
        return "OK", [self.prefix_payload]

    def list(self, directory='""', pattern="*"):
        # Dovecot answers BAD "Invalid pattern" when the directory is not the
        # literal `""`. The first version of this fake accepted anything and so
        # hid exactly that bug; keep it strict.
        if directory != '""':
            raise imaplib.IMAP4.error(f'LIST command error: BAD Invalid pattern (directory={directory!r})')
        name = pattern.strip('"')
        return ("OK", [b'(\\HasNoChildren) "." ' + name.encode()]) if name in self.existing else ("OK", [None])

    def create(self, name):
        self.created.append(name.strip('"'))
        self.existing.add(name.strip('"'))
        return "OK", [b"Create completed"]

    def subscribe(self, name):
        self.subscribed.append(name.strip('"'))
        return "OK", [b"Subscribe completed"]

    def append(self, folder, flags, date, raw):
        self.appended.append((folder, raw))
        return "OK", [b"Append completed"]


def _appender_with(fake, config):
    from mail_renderer.imap_append import ImapAppender

    appender = ImapAppender(config)
    appender._imap = fake
    appender._prefix = appender._personal_prefix()
    return appender


def test_drafts_folder_is_qualified_with_the_server_namespace(config: RendererConfig):
    """Hetzner rejects a bare `Drafts`: everything lives under the INBOX. namespace.

    Real failure this reproduces:
      APPEND to Drafts returned NO: Client tried to access nonexistent namespace.
    """
    fake = FakeImap(existing={"INBOX.Drafts"})
    _appender_with(fake, config).append("Drafts", b"raw message")
    assert fake.appended[0][0] == "INBOX.Drafts"
    assert fake.created == []  # already existed


def test_missing_drafts_folder_is_created_and_subscribed(config: RendererConfig):
    """A fresh mailbox has no Drafts folder, so the first APPEND must create it."""
    fake = FakeImap(existing=set())
    _appender_with(fake, config).append("Drafts", b"raw message")
    assert fake.created == ["INBOX.Drafts"]
    assert fake.subscribed == ["INBOX.Drafts"]
    assert fake.appended[0][0] == "INBOX.Drafts"


def test_server_without_a_namespace_prefix_is_left_alone(config: RendererConfig):
    """Portability: a server reporting no prefix must not gain one."""
    fake = FakeImap(prefix=b'(("" "/")) NIL NIL', existing={"Drafts"})
    _appender_with(fake, config).append("Drafts", b"raw message")
    assert fake.appended[0][0] == "Drafts"
