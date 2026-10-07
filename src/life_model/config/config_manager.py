# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deprecated process-global configuration shim.

Each :class:`~life_model.model.LifeModel` owns its own :class:`FinancialConfig` (``model.config``),
built from ``LifeModel(config=..., scenario=...)``. Mutating this global therefore does **not**
affect any model; it only changes the fallback used by module-level helpers that are called
without a ``config`` argument. Use ``LifeModel(scenario=...)`` or pass a ``FinancialConfig``
instead. This module will be removed in a future release.
"""

import warnings
from typing import Any, Optional

from .financial_config import FinancialConfig, default_financial_config
from .scenarios import get_scenario, list_scenarios

_DEPRECATION_MESSAGE = (
    "life_model.config.config_manager.config is deprecated and will be removed in a future release. "
    "It does not affect LifeModel instances; pass LifeModel(config=..., scenario=...) instead, or use "
    "life_model.config.financial_config.default_financial_config() for the packaged defaults."
)


def _warn() -> None:
    warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=3)


class GlobalConfigManager:
    """Deprecated global configuration manager (see module docstring)."""

    _instance: Optional["GlobalConfigManager"] = None

    # Singleton: always returns the one shared instance, even when called on a subclass.
    def __new__(cls) -> "GlobalConfigManager":  # noqa: PYI034
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def financial(self) -> FinancialConfig:
        """The shared packaged-defaults config (the fallback for helpers called without ``config``)."""
        _warn()
        return default_financial_config()

    def apply_scenario(self, scenario_name: str, overrides: dict[str, Any] | None = None) -> None:
        """Apply scenario overrides to the shared fallback config (does not affect models)."""
        _warn()
        if overrides is None:
            overrides = get_scenario(scenario_name)
        default_financial_config().apply_scenario(scenario_name, overrides)

    def apply_predefined_scenario(self, scenario_name: str) -> None:
        """Apply a predefined scenario to the shared fallback config (does not affect models)."""
        _warn()
        default_financial_config().apply_scenario(scenario_name, get_scenario(scenario_name))

    def list_available_scenarios(self) -> list:
        """Get a list of all available predefined scenarios"""
        _warn()
        return list_scenarios()

    def reset_to_defaults(self) -> None:
        """Reset the shared fallback config to the packaged defaults."""
        _warn()
        default_financial_config().reset_to_defaults()

    def get_current_scenario(self) -> str | None:
        """Get the scenario applied to the shared fallback config"""
        _warn()
        return default_financial_config().scenario


# Deprecated global configuration instance
config = GlobalConfigManager()
