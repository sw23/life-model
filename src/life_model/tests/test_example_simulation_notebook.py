# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import os
# Set JUPYTER_PLATFORM_DIRS before importing Jupyter modules to avoid deprecation warning
os.environ['JUPYTER_PLATFORM_DIRS'] = '1'

import unittest
import nbformat
from nbconvert.preprocessors import ExecutePreprocessor
    
def get_repo_root():
    """Find the root directory of the project.
    
    Returns:
        str: The absolute path to the project root directory.
    """
    # Navigate from the tests directory up to the project root
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.dirname(current_dir)

class JupyterNotebookTestBase(unittest.TestCase):
    """Base test class for testing Jupyter notebooks.
    
    This class provides utility methods for executing Jupyter notebooks
    and verifying they run without errors. Subclasses should override
    the notebook_path method or property to specify which notebook to test.
    """
    
    @property
    def notebook_path(self):
        """Return the path to the notebook to be tested.
        
        This method should be overridden by subclasses.
        
        Returns:
            str: The absolute path to the notebook file.
        
        Raises:
            NotImplementedError: If the subclass does not override this method.
        """
        raise NotImplementedError("Subclasses must override notebook_path")
    
    def _execute_notebook(self):
        """Execute the notebook and verify it runs without errors.
        
        This is a helper method that should be called by test methods in subclasses.
        """
        # Ensure notebook path exists
        notebook_path = self.notebook_path
        self.assertTrue(os.path.exists(notebook_path), 
                        f"Notebook not found at expected path: {notebook_path}")
        
        # Load the notebook
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)
        
        # Configure the notebook executor
        execute_preprocessor = ExecutePreprocessor(
            timeout=600,  # Allow up to 10 minutes for execution
            kernel_name='python3'
        )
        
        try:
            # Execute the notebook
            execute_preprocessor.preprocess(
                notebook, 
                {'metadata': {'path': os.path.dirname(notebook_path)}}
            )
        except Exception as e:
            self.fail(f"Error executing the notebook: {str(e)}")


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