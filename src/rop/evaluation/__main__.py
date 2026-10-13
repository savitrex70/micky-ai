"""Module entry point for ``python -m rop.evaluation``."""

from __future__ import annotations

import sys

from rop.evaluation.harness import main

if __name__ == "__main__":
    sys.exit(main())
