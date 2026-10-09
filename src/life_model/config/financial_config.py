# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from importlib.resources import files
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from .models import (
    AccountsConfig,
    DebtConfig,
    DependentsConfig,
    EconomyConfig,
    EquityCompConfig,
    EstateConfig,
    FinancialConfigModel,
    HealthcareConfig,
    HousingConfig,
    InsuranceConfig,
    RetirementConfig,
    SocialSecurityConfig,
    TaxBracketsConfig,
    TaxConfig,
    YearlyTaxParameters,
)

if TYPE_CHECKING:
    from ..tax.federal import FilingStatus


class FinancialConfig:
    """Configuration for financial parameters, limits, and rates.

    The validated Pydantic model (:class:`FinancialConfigModel`) is *the* runtime
    object: domain code reads typed attributes via the ``tax``/``retirement``/...
    properties instead of navigating an untyped dict. Each :class:`~life_model.model.LifeModel`
    owns its own instance (``model.config``); module-level helpers that take an optional
    ``config`` fall back to :func:`default_financial_config`.
    """

    def __init__(self, config_file: str | None = None, scenario: str | None = None):
        """Initialize financial configuration from YAML file

        Args:
            config_file: Path to configuration file. If None, uses packaged defaults.
            scenario: Optional scenario name to apply after loading defaults.
        """
        self.config_file = config_file
        self.scenario: str | None = None
        self._model: FinancialConfigModel
        self._load()
        if scenario is not None:
            from .scenarios import get_scenario

            self.apply_scenario(scenario, get_scenario(scenario))

    def _load(self) -> None:
        """Load and validate the configuration file (packaged defaults when no file is given)."""
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

    def reset_to_defaults(self) -> None:
        """Reload the configuration file, discarding any applied scenario."""
        self._load()
        self.scenario = None

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

    @property
    def housing(self) -> HousingConfig:
        return self._model.housing

    @property
    def estate(self) -> EstateConfig:
        return self._model.estate

    @property
    def economy(self) -> EconomyConfig:
        return self._model.economy

    @property
    def healthcare(self) -> HealthcareConfig:
        return self._model.healthcare

    @property
    def dependents(self) -> DependentsConfig:
        return self._model.dependents

    @property
    def equity_comp(self) -> EquityCompConfig:
        return self._model.equity_comp

    def tax_year(self, year: int, inflation_factor: float = 1.0) -> YearlyTaxParameters:
        """Get the tax parameters applicable to a given calendar year.

        Years present in the table return their published values. Years outside
        the table are projected by the documented rule: years before the earliest
        published year use the earliest entry, years after the latest published
        year are frozen at the latest entry, and gaps within the range use the most
        recent published year at or before the requested year. The returned object
        has ``year`` stamped with the requested year.

        For years beyond the last published year, pass ``inflation_factor`` (the cumulative
        price growth from the last published year to ``year``, e.g. ``1.34`` for +34%) to
        index the dollar-denominated parameters — bracket thresholds, standard deduction,
        and contribution limits — instead of freezing them. Values are rounded with IRS-style
        conventions (see :meth:`_project_tax_params`). The default ``1.0`` reproduces the
        frozen-at-latest behavior.
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

        params = table[chosen].model_copy(update={"year": year})
        if year > published_years[-1] and inflation_factor and inflation_factor != 1.0:
            params = self._project_tax_params(params, inflation_factor)
        return params

    def year_view(self, params: YearlyTaxParameters, inflation_factor: float = 1.0) -> "FinancialConfig":
        """A config for one simulated year: this config with ``params``' values swapped in.

        The year-table values replace the static ones everywhere the model reads them: the federal
        standard deduction and brackets, the Social Security wage base (FICA and AIME share it), and
        the 401k, IRA and HSA contribution limits. Preferential capital-gains brackets are not in the
        year table; past the last published year they are scaled by ``inflation_factor`` (the same
        factor the table values were projected with), otherwise left as configured.

        The view is a shallow copy that shares every other sub-model with this config, so it must be
        treated as read-only.
        """
        model = self._model
        federal = model.tax.federal
        capital_gains = federal.capital_gains
        if inflation_factor and inflation_factor != 1.0:
            capital_gains = TaxBracketsConfig(
                **{
                    status: [self._scale_bracket(b, inflation_factor) for b in rows]
                    for status, rows in capital_gains.model_dump().items()
                    if rows is not None
                }
            )
        tax = model.tax.model_copy(
            update={
                "federal": federal.model_copy(
                    update={
                        "standard_deduction": params.standard_deduction,
                        "tax_brackets": params.tax_brackets,
                        "capital_gains": capital_gains,
                    }
                ),
                "fica": model.tax.fica.model_copy(update={"social_security_max_income": params.ss_wage_base}),
            }
        )
        retirement = model.retirement.model_copy(
            update={
                "job_401k_contrib_limit": model.retirement.job_401k_contrib_limit.model_copy(
                    update={"base": params.limit_401k_base, "catch_up_amount": params.limit_401k_catch_up}
                ),
                "ira": model.retirement.ira.model_copy(update={"contribution_limit": params.limit_ira}),
            }
        )
        accounts = model.accounts.model_copy(
            update={
                "hsa": model.accounts.hsa.model_copy(
                    update={
                        "contribution_limit": params.limit_hsa_self,
                        "contribution_limit_family": params.limit_hsa_family,
                    }
                )
            }
        )
        view = object.__new__(FinancialConfig)
        view.config_file = self.config_file
        view.scenario = self.scenario
        view._model = model.model_copy(update={"tax": tax, "retirement": retirement, "accounts": accounts})
        return view

    @staticmethod
    def _scale_bracket(bracket, factor: float) -> list:
        """Scale a ``[lower, upper, rate]`` bracket's thresholds by ``factor`` (nearest $50)."""
        low, high, rate = bracket
        low = 0 if low == 0 else int(round(low * factor / 50) * 50)
        high = high if high == float("inf") else int(round(high * factor / 50) * 50)
        return [low, high, rate]

    @staticmethod
    def _project_tax_params(params: YearlyTaxParameters, factor: float) -> "YearlyTaxParameters":
        """Index dollar-denominated tax parameters by ``factor`` with IRS-style rounding.

        Bracket rates and the RMD start age are structural and left unchanged; only dollar
        thresholds and limits are scaled. Rounding bases follow published IRS/SSA conventions
        (standard deduction & HSA to the nearest $50, brackets to the nearest $50, retirement
        limits to the nearest $500, the IRA catch-up and gift exclusion to the nearest $1,000,
        and the Social Security wage base to the nearest $300).
        """

        def round_to(value: float, base: int) -> int:
            return int(round(value / base) * base)

        def scale_bracket(bracket):
            low, high, rate = bracket
            low = 0 if low == 0 else round_to(low * factor, 50)
            high = high if high == float("inf") else round_to(high * factor, 50)
            return [low, high, rate]

        data = params.model_dump()
        sd = data["standard_deduction"]
        sd["single"] = round_to(sd["single"] * factor, 50)
        sd["married_filing_jointly"] = round_to(sd["married_filing_jointly"] * factor, 50)
        if sd.get("head_of_household") is not None:
            sd["head_of_household"] = round_to(sd["head_of_household"] * factor, 50)
        if sd.get("married_filing_separately") is not None:
            sd["married_filing_separately"] = round_to(sd["married_filing_separately"] * factor, 50)
        for status in ("single", "married_filing_jointly", "head_of_household", "married_filing_separately"):
            if data["tax_brackets"].get(status) is not None:
                data["tax_brackets"][status] = [scale_bracket(b) for b in data["tax_brackets"][status]]
        data["ss_wage_base"] = round_to(data["ss_wage_base"] * factor, 300)
        data["limit_401k_base"] = round_to(data["limit_401k_base"] * factor, 500)
        data["limit_401k_catch_up"] = round_to(data["limit_401k_catch_up"] * factor, 500)
        data["limit_ira"] = round_to(data["limit_ira"] * factor, 500)
        data["limit_ira_catch_up"] = round_to(data["limit_ira_catch_up"] * factor, 1000)
        data["limit_hsa_self"] = round_to(data["limit_hsa_self"] * factor, 50)
        data["limit_hsa_family"] = round_to(data["limit_hsa_family"] * factor, 50)
        data["gift_exclusion"] = round_to(data["gift_exclusion"] * factor, 1000)
        # rmd_start_age is a structural (age) parameter, not a dollar amount — leave it.
        return YearlyTaxParameters(**data)

    # ------------------------------------------------------------------
    # Convenience methods (typed, read from the model)
    # ------------------------------------------------------------------
    def get_federal_standard_deduction(self, filing_status: "FilingStatus") -> float:
        """Get federal standard deduction for filing status.

        HEAD_OF_HOUSEHOLD uses its own configured value when present and falls back to
        ``single`` when the config carries no head_of_household data (documented behavior).
        """
        deduction = self._model.tax.federal.standard_deduction
        if filing_status.value == 2:
            return deduction.married_filing_jointly
        if filing_status.value == 3 and deduction.head_of_household is not None:
            return deduction.head_of_household
        if filing_status.value == 4:
            if deduction.married_filing_separately is not None:
                return deduction.married_filing_separately
            return deduction.married_filing_jointly / 2
        return deduction.single

    def get_federal_tax_brackets(self, filing_status: "FilingStatus") -> list:
        """Get federal tax brackets for filing status (HEAD_OF_HOUSEHOLD falls back to single)."""
        brackets = self._model.tax.federal.tax_brackets
        if filing_status.value == 2:
            return brackets.married_filing_jointly
        if filing_status.value == 3 and brackets.head_of_household is not None:
            return brackets.head_of_household
        if filing_status.value == 4:
            return self._separate_brackets(brackets)
        return brackets.single

    def get_capital_gains_brackets(self, filing_status: "FilingStatus") -> list:
        """Get preferential capital-gains brackets for filing status (HEAD_OF_HOUSEHOLD falls back
        to single)."""
        brackets = self._model.tax.federal.capital_gains
        if filing_status.value == 2:
            return brackets.married_filing_jointly
        if filing_status.value == 3 and brackets.head_of_household is not None:
            return brackets.head_of_household
        if filing_status.value == 4:
            return self._separate_brackets(brackets)
        return brackets.single

    @staticmethod
    def _separate_brackets(brackets: TaxBracketsConfig) -> list:
        """Married-filing-separately brackets: configured, else the joint thresholds halved."""
        if brackets.married_filing_separately is not None:
            return brackets.married_filing_separately
        return [[low / 2, high / 2, rate] for low, high, rate in brackets.married_filing_jointly]

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
    def apply_scenario(self, scenario: str, overrides: dict[str, Any]) -> None:
        """Apply scenario overrides, re-validating the merged config.

        Overrides are deep-merged into the current configuration and re-validated
        through :class:`FinancialConfigModel`, so a misspelled key or an
        out-of-range value in a scenario raises an error instead of silently
        creating a dead branch.
        """
        merged = self._deep_merge(self._model.model_dump(), overrides)
        self._propagate_to_tax_years(merged, overrides)
        try:
            self._model = FinancialConfigModel(**merged)
        except ValidationError as e:
            raise ValueError(f"Invalid scenario '{scenario}': {e}")
        self.scenario = scenario

    #: Static config paths whose values the per-year table also carries, mapped to the year-entry
    #: field. Simulated years read the year table, so a scenario that overrides one of these static
    #: values is applied to every year entry too (see :meth:`_propagate_to_tax_years`).
    _YEAR_TABLE_FIELDS = (
        (("tax", "federal", "standard_deduction"), "standard_deduction"),
        (("tax", "federal", "tax_brackets"), "tax_brackets"),
        (("tax", "fica", "social_security_max_income"), "ss_wage_base"),
        (("retirement", "job_401k_contrib_limit", "base"), "limit_401k_base"),
        (("retirement", "job_401k_contrib_limit", "catch_up_amount"), "limit_401k_catch_up"),
        (("retirement", "ira", "contribution_limit"), "limit_ira"),
        (("accounts", "hsa", "contribution_limit"), "limit_hsa_self"),
        (("accounts", "hsa", "contribution_limit_family"), "limit_hsa_family"),
    )

    @classmethod
    def _propagate_to_tax_years(cls, merged: dict[str, Any], overrides: dict[str, Any]) -> None:
        """Copy scenario overrides of static year-table fields into every ``tax_years`` entry.

        Without this, a scenario such as ``high_tax`` that sets ``tax.federal.tax_brackets`` would
        change only the static fallback while every simulated year kept the published table. Dict
        values (per-filing-status deductions and brackets) are merged per status, so overriding
        ``single`` alone leaves the other statuses' year values intact. Explicit ``tax_years``
        entries in the same scenario were merged first and are overwritten by the static override.
        """
        for path, field in cls._YEAR_TABLE_FIELDS:
            node: Any = overrides
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    break
                node = node[key]
            else:
                for entry in merged.get("tax_years", {}).values():
                    if isinstance(node, dict) and isinstance(entry.get(field), dict):
                        entry[field] = cls._deep_merge(entry[field], node)
                    else:
                        entry[field] = node

    @staticmethod
    def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        """Recursively merge ``overrides`` into a copy of ``base`` (dicts only)."""
        result = dict(base)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = FinancialConfig._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # Social Security historical tables (typed helpers) -----------------
    def get_avg_wage_index_table(self) -> dict[int, float]:
        """Get the full average wage index table."""
        return self._model.social_security.avg_wage_index

    def get_cost_of_living_adj_table(self) -> dict[int, float]:
        """Get the full cost-of-living adjustment table."""
        return self._model.social_security.cost_of_living_adj

    def get_bend_points_table(self) -> dict[int, list[int]]:
        """Get the full bend-points table."""
        return self._model.social_security.bend_points


_default_config: FinancialConfig | None = None


def default_financial_config() -> FinancialConfig:
    """Return the shared packaged-defaults config, loading it on first use.

    This is the fallback for module-level helpers called without a ``config``. Models never
    use it: each :class:`~life_model.model.LifeModel` builds its own instance. Loading is lazy
    so that ``import life_model`` performs no file I/O.
    """
    global _default_config
    if _default_config is None:
        _default_config = FinancialConfig()
    return _default_config


def resolve_financial_config(config: FinancialConfig | None) -> FinancialConfig:
    """Return ``config`` if given, else the packaged defaults (see :func:`default_financial_config`)."""
    return config if config is not None else default_financial_config()
