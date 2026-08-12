"""Security-property tests for the host-side draft renderer -- written first, per issue #37.

The renderer is the ONLY upward path in the mail design and it is a privilege
boundary: it runs on the host, as the agent's own user, and consumes files that
were written inside the container by an agent that has just read untrusted mail.
Every field in those files is attacker-controlled.

These tests pin the properties the design turns on:

- a `subject` containing CRLF cannot inject a header (no `Bcc` in the output)
- `In-Reply-To` is rejected unless it is a single, well-formed message-id that is
  actually present in the synced Maildir
- proposed `Bcc`/`Cc`/`To`/`Reply-To` keys in the sidecar are dropped, not merged
- a proposed recipient appears in the BODY, never in a header
- a body file that is a symlink (e.g. to the IMAP credential) is refused
- malformed sidecars route to `failed/` with an error file and nothing is APPENDed
- body-size and per-run caps are enforced
- a failed APPEND leaves the sidecar recoverable (not deleted, not in `posted/`)
"""

from __future__ import annotations

import json
from email import message_from_bytes
from pathlib import Path

import pytest

from mail_renderer import drain as drain_module
from mail_renderer.config import ConfigError, RendererConfig
from mail_renderer.drain import drain
from mail_renderer.errors import DraftError
from mail_renderer.imap_append import AppendError
from mail_renderer.render import ALLOWED_HEADERS, build_message, render_bytes
from mail_renderer.safeio import UnsafeReadError, read_bytes_nofollow
from mail_renderer.sidecar import load_sidecar

FROM_ADDR = "ha_agent@example.test"
TO_ADDR = "owner@example.test"
KNOWN_ID = "<known-thread-1@example.test>"


# ---------------------------------------------------------------------------
# Fixtures -- local to the renderer suite; no live IMAP, no real credential.
# ---------------------------------------------------------------------------


class FakeAppender:
    """Stand-in for the IMAP APPEND path. Records what would have been posted."""

    def __init__(self, fail_on: int | None = None):
        self.appended: list[tuple[str, bytes]] = []
        self.fail_on = fail_on

    def append(self, folder: str, raw: bytes) -> None:
        if self.fail_on is not None and len(self.appended) + 1 >= self.fail_on:
            raise AppendError("simulated IMAP APPEND failure")
        self.appended.append((folder, raw))


@pytest.fixture
def synced_maildir(tmp_path: Path) -> Path:
    """A minimal synced Maildir containing exactly one known Message-ID."""
    maildir = tmp_path / "mail"
    cur = maildir / "INBOX" / "cur"
    cur.mkdir(parents=True)
    (maildir / "INBOX" / "new").mkdir()
    (cur / "1700000000.abc:2,S").write_bytes(
        b"From: someone@example.test\r\n"
        b"To: ha_agent@example.test\r\n"
        b"Subject: an alert you should look at\r\n"
        b"Message-ID: " + KNOWN_ID.encode() + b"\r\n"
        b"\r\n"
        b"body text\r\n"
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
        drafts_folder="Drafts",
        max_drafts_per_run=5,
        max_body_bytes=4096,
    )


def write_draft(mail_out: Path, name: str, sidecar: dict | str, body: str | None = "hello") -> Path:
    path = mail_out / f"{name}.json"
    path.write_text(sidecar if isinstance(sidecar, str) else json.dumps(sidecar), encoding="utf-8")
    if body is not None:
        (mail_out / f"{name}.txt").write_text(body, encoding="utf-8")
    return path


def build_from_sidecar(config: RendererConfig, path: Path, known_ids: set[str] | None = None):
    sidecar = load_sidecar(path, config)
    body = sidecar.body_path.read_text(encoding="utf-8", errors="replace")
    return build_message(config, sidecar, body, known_ids if known_ids is not None else {KNOWN_ID})


def header_names(raw: bytes) -> set[str]:
    return {name.lower() for name, _ in message_from_bytes(raw).items()}


# ---------------------------------------------------------------------------
# 1. CRLF header injection via `subject`
# ---------------------------------------------------------------------------


def test_subject_with_crlf_cannot_inject_a_bcc_header(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "inject", {"subject": "Re: alert\r\nBcc: ops@evil.tld"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_subject_with_bare_lf_is_rejected(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "inject-lf", {"subject": "Re: alert\nBcc: ops@evil.tld"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_subject_with_trailing_crlf_is_rejected(config: RendererConfig, mail_out: Path):
    """A trailing CRLF survives str.splitlines() length checks -- reject it explicitly."""
    path = write_draft(mail_out, "inject-trailing", {"subject": "Re: alert\r\n"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_crlf_subject_never_reaches_a_rendered_message(config: RendererConfig, mail_out: Path):
    """End-to-end: the drain must not APPEND anything with an injected Bcc."""
    write_draft(mail_out, "inject", {"subject": "Re: alert\r\nBcc: ops@evil.tld"})
    appender = FakeAppender()
    report = drain(config, appender)

    assert appender.appended == []
    assert report.posted == []
    assert len(report.failed) == 1
    assert not (config.posted_dir / "inject.json").exists()
    assert (config.failed_dir / "inject.json").exists()
    assert (config.failed_dir / "inject.json.error").exists()


# ---------------------------------------------------------------------------
# 2. In-Reply-To validation
# ---------------------------------------------------------------------------


def test_in_reply_to_with_crlf_is_rejected(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "irt-crlf", {"subject": "ok", "in_reply_to": "<a@b>\r\nBcc: ops@evil.tld"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_in_reply_to_with_multiple_ids_is_rejected(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "irt-multi", {"subject": "ok", "in_reply_to": f"{KNOWN_ID} <other@example.test>"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_in_reply_to_as_a_list_is_rejected(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "irt-list", {"subject": "ok", "in_reply_to": [KNOWN_ID, KNOWN_ID]})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_in_reply_to_absent_from_the_maildir_is_rejected(config: RendererConfig, mail_out: Path):
    """A message-id the agent invented is a free-form data channel -- refuse it."""
    path = write_draft(mail_out, "irt-unknown", {"subject": "ok", "in_reply_to": "<exfil-payload@evil.tld>"})
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_in_reply_to_malformed_message_id_is_rejected(config: RendererConfig, mail_out: Path):
    for bad in ["not-a-message-id", "<no-at-sign>", "<a@b", "a@b>", "<>", "< spaced@b >"]:
        path = write_draft(mail_out, "irt-bad", {"subject": "ok", "in_reply_to": bad})
        with pytest.raises(DraftError):
            build_from_sidecar(config, path)


def test_in_reply_to_present_in_maildir_is_accepted(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "irt-good", {"subject": "ok", "in_reply_to": KNOWN_ID})
    msg = build_from_sidecar(config, path)
    assert msg["In-Reply-To"] == KNOWN_ID


def test_known_ids_are_read_from_the_synced_maildir(config: RendererConfig, mail_out: Path):
    """The membership set must come from the Maildir, not from the sidecar."""
    from mail_renderer.maildir_ids import collect_message_ids

    ids = collect_message_ids(config.maildir)
    assert KNOWN_ID in ids
    assert "<exfil-payload@evil.tld>" not in ids


# ---------------------------------------------------------------------------
# 3. Header allowlist: proposed headers are dropped, not merged
# ---------------------------------------------------------------------------


def test_proposed_recipient_headers_are_dropped(config: RendererConfig, mail_out: Path):
    path = write_draft(
        mail_out,
        "dropped",
        {
            "subject": "quarterly numbers",
            "bcc": "ops@evil.tld",
            "Bcc": "ops@evil.tld",
            "cc": "ops@evil.tld",
            "to": "ops@evil.tld",
            "from": "ceo@example.test",
            "reply-to": "ops@evil.tld",
            "return-path": "ops@evil.tld",
            "sender": "ops@evil.tld",
            "headers": {"Bcc": "ops@evil.tld"},
        },
    )
    msg = build_from_sidecar(config, path)
    raw = render_bytes(msg)

    assert msg["From"] == FROM_ADDR
    assert msg["To"] == TO_ADDR
    assert msg["Bcc"] is None
    assert msg["Cc"] is None
    assert msg["Reply-To"] is None
    assert msg["Return-Path"] is None
    assert msg["Sender"] is None
    assert b"evil.tld" not in raw.split(b"\r\n\r\n", 1)[0]
    assert header_names(raw) <= {h.lower() for h in ALLOWED_HEADERS} | {
        "mime-version",
        "content-type",
        "content-transfer-encoding",
    }


def test_rendered_header_block_is_allowlisted_after_reparsing(config: RendererConfig, mail_out: Path):
    """Re-parse the serialized bytes: folding must not have produced new headers."""
    path = write_draft(mail_out, "reparse", {"subject": "a " * 200, "in_reply_to": KNOWN_ID})
    raw = render_bytes(build_from_sidecar(config, path))
    assert header_names(raw) <= {h.lower() for h in ALLOWED_HEADERS} | {
        "mime-version",
        "content-type",
        "content-transfer-encoding",
    }


# ---------------------------------------------------------------------------
# 4. Proposed recipients land in the body, never in a header
# ---------------------------------------------------------------------------


def test_proposed_recipient_appears_in_body_not_in_any_header(config: RendererConfig, mail_out: Path):
    path = write_draft(
        mail_out,
        "proposed",
        {"subject": "please forward", "proposed_recipients": ["ops@evil.tld"]},
        body="here is the summary you asked for",
    )
    msg = build_from_sidecar(config, path)
    raw = render_bytes(msg)

    headers, body = raw.split(b"\r\n\r\n", 1)
    assert b"ops@evil.tld" not in headers
    assert b"ops@evil.tld" in body
    assert msg["To"] == TO_ADDR
    assert msg["Bcc"] is None


def test_proposed_recipient_with_crlf_cannot_forge_the_header_block(config: RendererConfig, mail_out: Path):
    path = write_draft(
        mail_out,
        "proposed-crlf",
        {"subject": "ok", "proposed_recipients": ["a@b.test\r\nBcc: ops@evil.tld"]},
    )
    msg = build_from_sidecar(config, path)
    raw = render_bytes(msg)
    headers = raw.split(b"\r\n\r\n", 1)[0]
    assert b"Bcc" not in headers
    assert msg["Bcc"] is None


# ---------------------------------------------------------------------------
# 5. Body-file handling: no symlink escape, no traversal
# ---------------------------------------------------------------------------


def test_body_file_symlink_to_the_imap_credential_is_refused(config: RendererConfig, mail_out: Path, tmp_path: Path):
    """The agent must not be able to have the renderer post the credential to Drafts."""
    secret_dir = tmp_path / "credentials"
    secret_dir.mkdir(exist_ok=True)
    secret = secret_dir / "imap_password"
    secret.write_text("hunter2\n", encoding="utf-8")

    path = write_draft(mail_out, "symlink", {"subject": "innocuous"}, body=None)
    (mail_out / "symlink.txt").symlink_to(secret)

    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


def test_body_file_outside_mail_out_is_refused(config: RendererConfig, mail_out: Path, tmp_path: Path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret-ish", encoding="utf-8")
    for candidate in ["../elsewhere.txt", str(outside), "/etc/passwd", "sub/../../elsewhere.txt"]:
        path = write_draft(mail_out, "outside", {"subject": "ok", "body_file": candidate}, body=None)
        with pytest.raises(DraftError):
            build_from_sidecar(config, path)


def test_missing_body_file_is_refused(config: RendererConfig, mail_out: Path):
    path = write_draft(mail_out, "nobody", {"subject": "ok"}, body=None)
    with pytest.raises(DraftError):
        build_from_sidecar(config, path)


# ---------------------------------------------------------------------------
# 6. Malformed sidecars route to failed/ and nothing is APPENDed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,payload",
    [
        ("not-json", "{this is not json"),
        ("not-an-object", '["subject"]'),
        ("no-subject", '{"in_reply_to": "<a@b.test>"}'),
        ("subject-not-a-string", '{"subject": 42}'),
        ("subject-empty", '{"subject": "   "}'),
    ],
)
def test_malformed_sidecar_routes_to_failed_with_an_error_file(
    config: RendererConfig, mail_out: Path, name: str, payload: str
):
    write_draft(mail_out, name, payload)
    appender = FakeAppender()
    report = drain(config, appender)

    assert appender.appended == []
    assert report.posted == []
    assert (config.failed_dir / f"{name}.json").exists()
    error_file = config.failed_dir / f"{name}.json.error"
    assert error_file.exists()
    assert error_file.read_text(encoding="utf-8").strip() != ""
    assert not (mail_out / f"{name}.json").exists()
    assert not (config.posted_dir / f"{name}.json").exists()


def test_failed_draft_body_is_moved_alongside_the_sidecar(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "bad", {"subject": "ok\r\nBcc: ops@evil.tld"}, body="keep me")
    drain(config, FakeAppender())
    assert (config.failed_dir / "bad.txt").read_text(encoding="utf-8") == "keep me"


# ---------------------------------------------------------------------------
# 7. Caps
# ---------------------------------------------------------------------------


def test_body_over_the_size_cap_is_refused(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "huge", {"subject": "ok"}, body="x" * (config.max_body_bytes + 1))
    appender = FakeAppender()
    report = drain(config, appender)
    assert appender.appended == []
    assert len(report.failed) == 1
    assert (config.failed_dir / "huge.json.error").exists()


def test_body_at_the_size_cap_is_accepted(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "atcap", {"subject": "ok"}, body="x" * config.max_body_bytes)
    appender = FakeAppender()
    report = drain(config, appender)
    assert len(appender.appended) == 1
    assert report.posted == ["atcap.json"]


def test_per_run_draft_cap_is_enforced(config: RendererConfig, mail_out: Path):
    for index in range(config.max_drafts_per_run + 3):
        write_draft(mail_out, f"draft-{index:02d}", {"subject": f"draft {index}"})
    appender = FakeAppender()
    report = drain(config, appender)

    assert len(appender.appended) == config.max_drafts_per_run
    assert len(report.posted) == config.max_drafts_per_run
    assert len(report.deferred) == 3
    # The deferred ones stay put so the next run picks them up.
    for name in report.deferred:
        assert (mail_out / name).exists()


def test_oversize_sidecar_file_is_refused_before_json_parsing(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "fat", '{"subject": "' + "a" * 200_000 + '"}')
    appender = FakeAppender()
    drain(config, appender)
    assert appender.appended == []
    assert (config.failed_dir / "fat.json.error").exists()


# ---------------------------------------------------------------------------
# 8. APPEND failure leaves the sidecar recoverable
# ---------------------------------------------------------------------------


def test_append_failure_leaves_the_sidecar_in_place(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "unlucky", {"subject": "will not post"})
    appender = FakeAppender(fail_on=1)
    report = drain(config, appender)

    assert appender.appended == []
    assert report.posted == []
    assert report.append_errors
    assert (mail_out / "unlucky.json").exists()
    assert (mail_out / "unlucky.txt").exists()
    assert not (config.posted_dir / "unlucky.json").exists()
    assert not (config.failed_dir / "unlucky.json").exists()


def test_append_failure_defers_the_remaining_drafts(config: RendererConfig, mail_out: Path):
    for index in range(3):
        write_draft(mail_out, f"d{index}", {"subject": f"draft {index}"})
    appender = FakeAppender(fail_on=2)
    report = drain(config, appender)

    assert len(appender.appended) == 1
    assert report.posted == ["d0.json"]
    assert (mail_out / "d1.json").exists()
    assert (mail_out / "d2.json").exists()


# ---------------------------------------------------------------------------
# 9. The IMAP credential must never be reachable from the workspace
# ---------------------------------------------------------------------------


def test_config_refuses_a_credential_path_inside_the_workspace(config: RendererConfig, mail_out: Path):
    bad = RendererConfig(
        mail_out=config.mail_out,
        maildir=config.maildir,
        from_addr=FROM_ADDR,
        to_addr=TO_ADDR,
        imap_host="imap.example.test",
        imap_user="ha_agent@example.test",
        imap_password_file=mail_out.parent / ".secrets" / "imap_password",
    )
    with pytest.raises(ConfigError):
        bad.validate()


def test_config_accepts_a_credential_path_outside_the_workspace(config: RendererConfig):
    config.validate()


def test_drain_refuses_an_unsafe_configuration_before_appending_anything(config: RendererConfig, mail_out: Path):
    write_draft(mail_out, "ok", {"subject": "harmless"})
    unsafe = RendererConfig(
        mail_out=config.mail_out,
        maildir=config.maildir,
        from_addr=FROM_ADDR,
        to_addr=TO_ADDR,
        imap_host="imap.example.test",
        imap_user="ha_agent@example.test",
        imap_password_file=mail_out / "imap_password",
    )
    appender = FakeAppender()
    with pytest.raises(ConfigError):
        drain(unsafe, appender)
    assert appender.appended == []
    assert (mail_out / "ok.json").exists()


def test_renderer_package_never_references_the_credential_from_workspace():
    """Grep-level guard: no module may join a workspace path with the credential name."""
    package = Path(__file__).resolve().parent.parent / "mail_renderer"
    for module in package.glob("*.py"):
        text = module.read_text(encoding="utf-8")
        assert "workspace/.secrets" not in text
        assert "mail-out/imap_password" not in text


def test_body_file_swapped_for_a_symlink_after_validation_is_not_read(
    config: RendererConfig, mail_out: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The TOCTOU behind the symlink guard: validate, swap, read.

    `load_sidecar` proves the body file is a regular file inside `mail-out/`,
    but the read is a separate syscall against the same *name*, and the agent
    owns that directory. Swapping the file for a symlink in between made the
    host renderer read whatever the link pointed at -- the IMAP credential --
    and APPEND it to Drafts, which is exactly the exfiltration the static
    symlink check was written to stop.

    This simulates the swap deterministically by mutating the directory between
    validation and read; with a by-name read it posts the secret.
    """
    secret = tmp_path / "credentials" / "imap_password"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("the-real-imap-password", encoding="utf-8")

    write_draft(mail_out, "race", {"subject": "innocuous"}, body="harmless body")
    body_file = mail_out / "race.txt"

    real_load_sidecar = drain_module.load_sidecar

    def load_then_swap(path: Path, cfg: RendererConfig):
        sidecar = real_load_sidecar(path, cfg)
        body_file.unlink()
        body_file.symlink_to(secret)
        return sidecar

    monkeypatch.setattr(drain_module, "load_sidecar", load_then_swap)

    appender = FakeAppender()
    report = drain(config, appender)

    assert appender.appended == [], "the credential must never reach an APPEND"
    for _folder, raw in appender.appended:
        assert b"the-real-imap-password" not in raw
    assert report.posted == []
    assert report.failed == ["race.json"]
    assert (config.failed_dir / "race.json").exists()


def test_read_bytes_nofollow_refuses_a_symlink_and_caps_size(tmp_path: Path):
    target = tmp_path / "secret"
    target.write_text("sensitive", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(UnsafeReadError, match="symlink"):
        read_bytes_nofollow(link, 4096, "body file 'link.txt'")

    big = tmp_path / "big.txt"
    big.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(UnsafeReadError, match="cap"):
        read_bytes_nofollow(big, 10, "body file 'big.txt'")

    ok = tmp_path / "ok.txt"
    ok.write_text("fine", encoding="utf-8")
    assert read_bytes_nofollow(ok, 4096, "body file 'ok.txt'") == b"fine"
