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
