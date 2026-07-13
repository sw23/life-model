# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pytest configuration for the SLM adviser tests.

Makes the RL modules, the source tree, and the repo root importable regardless of the pytest
rootdir or the launch directory:

* repo root so ``import slm`` (the product package) resolves,
* ``deepqlearning/`` so scoring can ``import baselines`` / ``environment`` / ``actions``,
* ``src/`` (prepended first so it wins) so ``life_model`` resolves from source.

This mirrors ``deepqlearning/tests/conftest.py`` — the RL modules use bare (non-package) imports,
so their directory must be on ``sys.path``.
"""

import os
import sys

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

sys.path.insert(0, os.path.join(_ROOT, "deepqlearning"))  # bare RL imports
sys.path.insert(0, _ROOT)  # `import slm`
sys.path.insert(0, os.path.join(_ROOT, "src"))  # `life_model` from source (wins)
