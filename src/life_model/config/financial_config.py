# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import warnings
from importlib.resources import files
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from .base_config import ScenarioConfig
from .models import (
    AccountsConfig,
    DebtConfig,
    FinancialConfigModel,
    InsuranceConfig,
    RetirementConfig,
    SocialSecurityConfig,
    TaxConfig,
    YearlyTaxParameters,
)

if TYPE_CHECKING:
    from ..tax.federal import FilingStatus


class FinancialConfig(ScenarioConfig):
    """Configuration for financial parameters, limits, and rates.

    The validated Pydantic model (:class:`FinancialConfigModel`) is *the* runtime
    object: domain code reads typed attributes via the ``tax``/``retirement``/...
    properties instead of navigating an untyped dict. The legacy ``get(dot_key)``
    accessor remains during the migration but emits a ``DeprecationWarning``.
    """

    def __init__(self, config_file: Optional[str] = None, scenario: Optional[str] = None):
        """Initialize financial configuration from YAML file

        Args:
            config_file: Path to configuration file. If None, uses packaged defaults.
            scenario: Optional scenario name to apply after loading defaults.
        """
        self.config_file = config_file
        self._model: FinancialConfigModel
        super().__init__(scenario=scenario)
        if scenario is not None:
            from .scenarios import get_scenario

            self.apply_scenario(scenario, get_scenario(scenario))

    def _initialize_defaults(self) -> None:
        """Load and validate the default financial configuration."""
        if self.config_file is None:
            data_file = files("life_model.config") / "data" / "financial_defaults.yaml"
            raw_config = yaml.safe_load(data_file.read_text(encoding="utf-8"))
        else:
            with open(self.config_file, "r") as f:
                raw_config = yaml.safe_load(f)

        try:
            self._model = FinancialConfigModel(**raw_config)
        except ValidationError as e:
            source = self.config_file or "packaged defaults"
            raise ValueError(f"Invalid configuration in {source}: {e}")

    # ------------------------------------------------------------------
    # Typed access to the validated configuration model
    # ------------------------------------------------------------------
    @property
    def model(self) -> FinancialConfigModel:
        """The validated configuration model."""
        return self._model

    @property
    def tax(self) -> TaxConfig:
        return self._model.tax

    @property
    def retirement(self) -> RetirementConfig:
        return self._model.retirement

    @property
    def social_security(self) -> SocialSecurityConfig:
        return self._model.social_security

    @property
    def accounts(self) -> AccountsConfig:
        return self._model.accounts

    @property
    def insurance(self) -> InsuranceConfig:
        return self._model.insurance

    @property
    def debt(self) -> DebtConfig:
        return self._model.debt

    def tax_year(self, year: int) -> YearlyTaxParameters:
        """Get the tax parameters applicable to a given calendar year.

        Years present in the table return their published values. Years outside
        the table are projected by the documented rule: years before the earliest
        published year use the earliest entry, years after the latest published
        year are frozen at the latest entry, and gaps within the range use the most
        recent published year at or before the requested year. The returned object
        has ``year`` stamped with the requested year.
        """
        table = self._model.tax_years
        published_years = sorted(table)
        if not published_years:
            raise ValueError("No tax_years table is configured")

        if year in table:
            chosen = year
        elif year < published_years[0]:
            chosen = published_years[0]
        elif year > published_years[-1]:
            chosen = published_years[-1]
        else:
            chosen = max(y for y in published_years if y <= year)

        return table[chosen].model_copy(update={"year": year})

    # ------------------------------------------------------------------
    # Convenience methods (typed, read from the model)
    # ------------------------------------------------------------------
    def get_federal_standard_deduction(self, filing_status: "FilingStatus") -> float:
        """Get federal standard deduction for filing status"""
        deduction = self._model.tax.federal.standard_deduction
        return deduction.single if filing_status.value == 1 else deduction.married_filing_jointly

    def get_federal_tax_brackets(self, filing_status: "FilingStatus") -> list:
        """Get federal tax brackets for filing status"""
        brackets = self._model.tax.federal.tax_brackets
        return brackets.single if filing_status.value == 1 else brackets.married_filing_jointly

    def get_job_401k_contrib_limit(self, age: int) -> int:
        """Get 401k contribution limit based on age"""
        limit = self._model.retirement.job_401k_contrib_limit
        return limit.base + (limit.catch_up_amount if age >= limit.catch_up_age else 0)

    def get_job_401k_annual_additions_limit(self) -> int:
        """Get the 415(c) overall annual-additions limit (employee + employer, per plan)."""
        return self._model.retirement.job_401k_contrib_limit.annual_additions_limit

    def get_max_tax_rate(self, filing_status: "FilingStatus") -> float:
        """Get maximum tax rate for filing status"""
        brackets = self.get_federal_tax_brackets(filing_status)
        return brackets[-1][2] if brackets else 0.0

    # ------------------------------------------------------------------
    # Scenario application (re-validated through Pydantic)
    # ------------------------------------------------------------------
    def apply_scenario(self, scenario: str, overrides: Dict[str, Any]) -> None:
        """Apply scenario overrides, re-validating the merged config.

        Overrides are deep-merged into the current configuration and re-validated
        through :class:`FinancialConfigModel`, so a misspelled key or an
        out-of-range value in a scenario raises an error instead of silently
        creating a dead branch.
        """
        merged = self._deep_merge(self._model.model_dump(), overrides)
        try:
            self._model = FinancialConfigModel(**merged)
        except ValidationError as e:
            raise ValueError(f"Invalid scenario '{scenario}': {e}")
        self.scenario = scenario

    @staticmethod
    def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge ``overrides`` into a copy of ``base`` (dicts only)."""
        result = dict(base)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = FinancialConfig._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ------------------------------------------------------------------
    # Deprecated dot-notation access (walks the validated model)
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Deprecated: read a value by dot-notation key.

        Retained during the migration to typed access. Prefer the ``tax``,
        ``retirement``, ``social_security``, ``accounts``, ``insurance`` and
        ``debt`` properties instead.
        """
        warnings.warn(
            "FinancialConfig.get() is deprecated; use the typed config properties "
            "(e.g. config.financial.tax.state.tax_rate) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        current: Any = self._model
        for part in key.split("."):
            if isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    try:
                        current = current[int(part)]
                    except (KeyError, ValueError):
                        return default
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return default
        return current

    # Social Security historical tables (typed helpers) -----------------
    def get_avg_wage_index_table(self) -> Dict[int, float]:
        """Get the full average wage index table."""
        return self._model.social_security.avg_wage_index

    def get_cost_of_living_adj_table(self) -> Dict[int, float]:
        """Get the full cost-of-living adjustment table."""
        return self._model.social_security.cost_of_living_adj

    def get_bend_points_table(self) -> Dict[int, List[int]]:
        """Get the full bend-points table."""
        return self._model.social_security.bend_points
