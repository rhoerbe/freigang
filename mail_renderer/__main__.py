"""Allow `python3 -m mail_renderer`."""

from __future__ import annotations

import sys

from mail_renderer.cli import main

if __name__ == "__main__":
    sys.exit(main())
