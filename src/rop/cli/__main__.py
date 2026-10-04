"""Module entry point for ``python -m rop.cli``."""

from __future__ import annotations

import sys

from rop.cli import main

if __name__ == "__main__":
    sys.exit(main())
