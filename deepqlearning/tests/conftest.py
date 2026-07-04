# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pytest configuration for the deep Q-learning tests.

Makes both the RL modules and the source tree importable regardless of the pytest rootdir or the
working directory the suite is launched from:

* ``deepqlearning/`` so ``import environment`` / ``agent`` / ``actions`` / ``baselines`` resolve.
* ``src/`` (prepended first so it wins) so ``life_model`` and its test helpers resolve from
  source. The notebook test depends on ``life_model.tests.notebook_test_base``, which is a test
  helper that is intentionally not shipped in the installed wheel, so it must come from ``src/``.
  This must happen before any test module imports ``life_model`` (e.g. via ``environment``),
  otherwise ``life_model`` would already be cached from the installed wheel and its ``tests``
  subpackage would be unavailable.
"""

import os
import sys

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))  # deepqlearning/
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "src")))  # src/
