"""Shared pytest fixtures for the mail_cli test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "mail"


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
