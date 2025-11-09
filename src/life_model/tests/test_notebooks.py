# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the ExampleSimulation.ipynb notebook."""

import os
import unittest
from .notebook_test_base import JupyterNotebookTestBase, get_repo_root


class TestExampleSimulationNotebook(JupyterNotebookTestBase):
    """Test class for the ExampleSimulation.ipynb notebook."""

    @property
    def notebook_path(self):
        """Return the path to the ExampleSimulation.ipynb notebook."""
        repo_root = get_repo_root()
        return os.path.join(repo_root, 'ExampleSimulation.ipynb')

    def test_notebook_execution(self):
        """Test that the ExampleSimulation.ipynb notebook executes without errors."""
        self._execute_notebook()


if __name__ == '__main__':
    unittest.main()
