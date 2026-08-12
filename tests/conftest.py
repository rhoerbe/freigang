"""Shared pytest fixtures for the mail_cli test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "mail"


@pytest.fixture(autouse=True, scope="session")
def _ensure_maildir_subdirs_exist() -> None:
    """Create the `new/` and `tmp/` siblings of each checked-in fixture Maildir's `cur/`.

    Git does not track empty directories, so a fresh clone ships only `cur/` for each fixture
    Maildir. `mailbox.Maildir` requires all three subdirectories to exist and raises otherwise,
    which fails every test that opens a fixture Maildir before any test code runs. Creating the
    directories here (rather than committing a placeholder file such as `.gitkeep` inside `new/`)
    avoids the placeholder itself being parsed as a message by `mailbox.Maildir`.
    """
    for maildir in FIXTURES_ROOT.iterdir():
        if not maildir.is_dir():
            continue
        for subdir in ("new", "tmp", "cur"):
            (maildir / subdir).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def security_maildir() -> Path:
    return FIXTURES_ROOT / "security"


@pytest.fixture
def mime_maildir() -> Path:
    return FIXTURES_ROOT / "mime"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _find_id_by_subject(entries, subject_substring: str) -> str:
    for entry in entries:
        if subject_substring in entry.subject:
            return entry.id
    raise AssertionError(f"No fixture message with subject containing {subject_substring!r}")


@pytest.fixture
def find_id_by_subject():
    return _find_id_by_subject
