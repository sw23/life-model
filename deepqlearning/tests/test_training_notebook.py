# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the Training_Example.ipynb notebook."""

import os
import sys
import tempfile
import unittest

# Add the src directory to the path to import the base test class
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from life_model.tests.notebook_test_base import JupyterNotebookTestBase, get_repo_root  # noqa: E402


class TestTrainingExampleNotebook(JupyterNotebookTestBase):
    """Test class for the Training_Example.ipynb notebook."""

    @property
    def notebook_path(self):
        """Return the path to the Training_Example.ipynb notebook."""
        repo_root = get_repo_root()
        return os.path.join(repo_root, 'deepqlearning', 'Training_Example.ipynb')

    def test_notebook_execution(self):
        """Test that the Training_Example.ipynb notebook executes without errors."""
        os.environ['NUM_EPISODES'] = '10'  # Set a shorter episode count for testing
        os.environ['OUTPUT_DIR'] = tempfile.mkdtemp()  # Use a temp directory for outputs
        # Disable weight-only loading to avoid issues with model saving
        # https://docs.pytorch.org/docs/stable/notes/serialization.html#torch-load-with-weights-only-true
        os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'
        self._execute_notebook()


if __name__ == '__main__':
    unittest.main()
