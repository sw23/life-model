"""Pytest configuration for the dashboard tests.

Adds the ``dashboard/`` directory to ``sys.path`` so ``import app`` resolves regardless of the
pytest rootdir or the working directory the suite is launched from.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
