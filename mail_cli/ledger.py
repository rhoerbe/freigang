"""Advisory processed-ledger.

Records message-ids the agent has already looked at via `mail show`, so
`mail ls` can display a marker. This is advisory ONLY: a ledger entry must
never hide a message from the listing or from `mail show`/`mail attach`. A
stale or corrupt ledger degrades gracefully to "nothing marked processed"
rather than hiding mail.
"""

from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    """A small JSON set of processed message ids, stored under the workspace."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # Advisory only: a corrupt ledger must never break mail access.
            return set()
        if not isinstance(data, list):
            return set()
        return {str(item) for item in data}

    def is_processed(self, entry_id: str) -> bool:
        return entry_id in self._load()

    def mark_processed(self, entry_id: str) -> None:
        processed = self._load()
        processed.add(entry_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(processed), indent=2) + "\n", encoding="utf-8")
