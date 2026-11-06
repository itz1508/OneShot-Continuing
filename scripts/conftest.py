"""Pytest configuration for tests under scripts/."""

import sys
from pathlib import Path

# The project-wide import path is configured in pyproject.toml.
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
