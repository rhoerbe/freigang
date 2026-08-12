"""MIME-decode coverage: base64, quoted-printable, HTML-only, multipart/alternative.

Lower priority than the security suite (a bad decode is immediately visible),
but required by issue #37's acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path

from mail_cli import bodytext
from mail_cli.mailstore import MailStore


def test_base64_body_decodes_to_plain_text(mime_maildir: Path, find_id_by_subject):
    store = MailStore(mime_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "Base64 body")
    _entry, msg = store.get_message(msg_id)

    assert msg.get("Content-Transfer-Encoding", "").lower() == "base64"

    body, source_type = bodytext.extract_body(msg)
    assert source_type == "text/plain"
    assert body == "Hello Base64 World\nSecond line.\n"


def test_quoted_printable_body_decodes_non_ascii(mime_maildir: Path, find_id_by_subject):
    store = MailStore(mime_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "Quoted-printable body")
    _entry, msg = store.get_message(msg_id)

    assert msg.get("Content-Transfer-Encoding", "").lower() == "quoted-printable"

    body, source_type = bodytext.extract_body(msg)
    assert source_type == "text/plain"
    assert body == "Héllo QP Wörld, café.\n"


def test_html_only_message_falls_back_to_stripped_text(mime_maildir: Path, find_id_by_subject):
    store = MailStore(mime_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "HTML only")
    _entry, msg = store.get_message(msg_id)

    assert msg.get_content_type() == "text/html"

    body, source_type = bodytext.extract_body(msg)
    assert source_type == "text/html"
    assert "<" not in body
    assert ">" not in body
    assert "Hello HTML World" in body
    assert "Second paragraph." in body


def test_multipart_alternative_prefers_plain_over_html(mime_maildir: Path, find_id_by_subject):
    store = MailStore(mime_maildir)
    entries = store.list_entries()
    msg_id = find_id_by_subject(entries, "Multipart alternative")
    _entry, msg = store.get_message(msg_id)

    assert msg.is_multipart()

    body, source_type = bodytext.extract_body(msg)
    assert source_type == "text/plain"
    assert body.strip() == "Plain version of the message."
    assert "<p>" not in body


def test_html_to_text_strips_tags_and_keeps_text():
    html = "<html><body><p>Hello <b>World</b></p><script>evil()</script><style>.x{}</style></body></html>"
    text = bodytext.html_to_text(html)
    assert "Hello World" in text
    assert "evil()" not in text
    assert "{}" not in text
    assert "<" not in text


def test_html_to_text_unescapes_entities():
    html = "<p>Tom &amp; Jerry &lt;3&gt;</p>"
    text = bodytext.html_to_text(html)
    assert text == "Tom & Jerry <3>"


def test_ls_reports_attachment_counts_from_mime_fixtures(mime_maildir: Path):
    store = MailStore(mime_maildir)
    entries = store.list_entries()
    # None of the MIME-decode fixtures carry attachments.
    assert all(e.attachment_count == 0 for e in entries)
    assert len(entries) == 4


def test_encoded_word_headers_are_decoded_and_flattened(tmp_path: Path):
    """Real mail carries RFC 2047 headers folded across lines.

    Undecoded, `mail ls` printed base64 and the folded continuation lines broke
    the table; worse, the agent would reason about the encoded text rather than
    the subject. The fixtures could not catch this because they use plain ASCII
    headers -- it only showed up against the real mailbox.
    """
    folder = tmp_path / "mail" / "INBOX"
    for sub in ("cur", "new", "tmp"):
        (folder / sub).mkdir(parents=True)
    (folder / "cur" / "1.a:2,S").write_bytes(
        b"From: =?utf-8?q?Rainer=20H=c3=b6rbe?= <r@example.test>\n"
        b"Subject: =?utf-8?B?Q0FTLTIzNTkzODkgRnJvbml1cyB3YXR0cGlsb3Q=?=\n"
        b" =?utf-8?B?IHNjaGFsdGV0IG5pY2h0IHVt?=\n"
        b"Message-ID: <enc-1@example.test>\n\nbody\n"
    )

    entry = MailStore(tmp_path / "mail").list_entries()[0]
    assert entry.from_addr == "Rainer Hörbe <r@example.test>"
    assert entry.subject == "CAS-2359389 Fronius wattpilot schaltet nicht um"
    assert "\n" not in entry.subject and "=?" not in entry.subject


def test_undecodable_header_falls_back_to_raw(tmp_path: Path):
    """A malformed encoding must not take the whole listing down."""
    folder = tmp_path / "mail" / "INBOX"
    for sub in ("cur", "new", "tmp"):
        (folder / sub).mkdir(parents=True)
    (folder / "cur" / "1.b:2,S").write_bytes(
        b"From: =?not-a-charset?q?whatever?= <r@example.test>\n"
        b"Subject: plain\nMessage-ID: <bad-1@example.test>\n\nbody\n"
    )
    entry = MailStore(tmp_path / "mail").list_entries()[0]
    assert entry.subject == "plain"
    assert "r@example.test" in entry.from_addr
