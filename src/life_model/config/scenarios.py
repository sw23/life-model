# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""
Predefined scenario configurations for common economic and regulatory conditions.
These scenarios allow users to easily adjust multiple configuration parameters
to model different economic environments without manually changing individual values.
"""

import yaml
from importlib.resources import files
from pathlib import Path
from typing import Dict, Any, Optional

# Optional user-supplied scenario directory. When set, it takes precedence over
# the scenarios packaged with life-model.
_user_scenario_dir: Optional[Path] = None


def set_scenario_directory(directory: Optional[str]) -> None:
    """Set a user-supplied directory to search for scenario YAML files.

    Scenarios found here take precedence over the ones packaged with life-model.

    Args:
        directory: Path to a directory containing ``<name>.yaml`` scenario files,
            or None to use only the packaged scenarios.
    """
    global _user_scenario_dir
    _user_scenario_dir = Path(directory) if directory is not None else None


def _load_scenario_from_yaml(filename: str) -> Dict[str, Any]:
    """Load a scenario configuration from a YAML file

    Args:
        filename: Name of the YAML file (without path)

    Returns:
        Dictionary containing scenario configuration

    Raises:
        FileNotFoundError: If the scenario file cannot be found
    """
    # A user-supplied directory takes precedence over packaged scenarios.
    if _user_scenario_dir is not None:
        user_path = _user_scenario_dir / filename
        if user_path.exists():
            with open(user_path, 'r') as f:
                return yaml.safe_load(f)

    packaged = files('life_model.config') / 'data' / 'scenarios' / filename
    if packaged.is_file():
        return yaml.safe_load(packaged.read_text(encoding='utf-8'))

    raise FileNotFoundError(f"Scenario file '{filename}' not found in any of the expected locations")


def get_scenario(name: str) -> Dict[str, Any]:
    """Get a predefined scenario by name

    Args:
        name: Name of the scenario

    Returns:
        Dictionary of configuration overrides for the scenario

    Raises:
        KeyError: If scenario name is not found
        FileNotFoundError: If the scenario file cannot be found
    """
    filename = f"{name}.yaml"
    try:
        return _load_scenario_from_yaml(filename)
    except FileNotFoundError:
        available = list_scenarios()
        raise KeyError(f"Scenario '{name}' not found. Available scenarios: {', '.join(available)}")


def list_scenarios() -> list:
    """Get a list of all available predefined scenarios"""
    scenarios = set()

    # Scenarios packaged with life-model.
    packaged_dir = files('life_model.config') / 'data' / 'scenarios'
    for entry in packaged_dir.iterdir():
        if entry.name.endswith('.yaml'):
            scenarios.add(entry.name[:-len('.yaml')])

    # User-supplied scenarios (take precedence but also add to the list).
    if _user_scenario_dir is not None and _user_scenario_dir.is_dir():
        for yaml_file in _user_scenario_dir.glob('*.yaml'):
            scenarios.add(yaml_file.stem)

    return sorted(scenarios)
