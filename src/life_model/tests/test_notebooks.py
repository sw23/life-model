# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import os
import sys
import tempfile
import json
import unittest

# First set the environment variable before any Jupyter imports
os.environ['JUPYTER_PLATFORM_DIRS'] = '1'

import nbformat  # noqa: E402
from nbconvert.preprocessors import ExecutePreprocessor  # noqa: E402
from jupyter_client import kernelspec  # noqa: E402


def get_repo_root():
    """Find the root directory of the project.

    Returns:
        str: The absolute path to the project root directory.
    """
    # Navigate from the tests directory up to the project root
    current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.dirname(current_dir)


def get_available_kernel():
    """Find an available Python kernel to use for executing notebooks.
    If no suitable kernel is found and we're in a tox environment, creates a temporary kernel.

    Returns:
        str: Name of an available or newly created Python kernel
    """
    ksm = kernelspec.KernelSpecManager()
    try:
        kernel_specs = ksm.get_all_specs()

        # Look for Python kernels, prioritizing python3
        if 'python3' in kernel_specs:
            return 'python3'

        # Look for any Python kernel
        for name, spec in kernel_specs.items():
            if 'python' in name.lower():
                return name

        # If we're in a tox environment and no suitable kernel found, create one
        if is_running_in_tox():
            return create_temporary_kernel()

    except Exception as e:
        print(f"Error finding kernels: {e}")
        # If we're in a tox environment, create a kernel
        if is_running_in_tox():
            return create_temporary_kernel()

    # Return python3 as a fallback (may fail but provides a clearer error)
    return 'python3'


def create_temporary_kernel():
    """Create a temporary kernel spec for the current Python interpreter.

    Returns:
        str: Name of the created kernel
    """
    print("Creating temporary kernel spec for current Python interpreter")
    kernel_name = f"python-tox-{os.getpid()}"

    # Create a temporary directory for the kernel spec
    temp_dir = tempfile.mkdtemp(prefix='kernel-')

    # Create the kernel.json file
    kernel_json = {
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": f"Python (Tox {sys.version_info[0]}.{sys.version_info[1]})",
        "language": "python",
        "interrupt_mode": "signal",
        "env": {},
    }

    # Write the kernel.json file
    with open(os.path.join(temp_dir, 'kernel.json'), 'w') as f:
        json.dump(kernel_json, f, indent=2)

    # Install the kernel spec
    ksm = kernelspec.KernelSpecManager()
    ksm.install_kernel_spec(temp_dir, kernel_name, user=True, replace=True)
    print(f"Installed temporary kernel: {kernel_name}")

    return kernel_name


def is_running_in_tox():
    """Determine if the test is running in a tox environment.

    Returns:
        bool: True if running in tox, False otherwise
    """
    return 'TOX_ENV_NAME' in os.environ


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

        Raises:
            AssertionError: If the notebook execution fails or no suitable kernel can be found
        """
        # Ensure notebook path exists
        notebook_path = self.notebook_path
        self.assertTrue(os.path.exists(notebook_path),
                        f"Notebook not found at expected path: {notebook_path}")

        # Load the notebook
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=4)

        # Get available kernel
        kernel_name = get_available_kernel()
        if kernel_name is None:
            self.fail("Could not find or create a suitable Jupyter kernel for notebook execution")

        print(f"Using kernel: {kernel_name}")

        # Configure the notebook executor
        execute_preprocessor = ExecutePreprocessor(
            timeout=600,  # Allow up to 10 minutes for execution
            kernel_name=kernel_name
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
