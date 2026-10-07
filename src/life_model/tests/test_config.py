# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
import warnings

from ..config.config_manager import GlobalConfigManager
from ..config.financial_config import FinancialConfig, default_financial_config, resolve_financial_config
from ..tax.federal import FilingStatus


class TestFinancialConfigApi(unittest.TestCase):
    """FinancialConfig exposes typed access only; the old dict API is gone."""

    def test_untyped_dict_api_removed(self):
        """set/update/get_all used to write to a dict nothing read (silent no-ops); get() was deprecated."""
        config = FinancialConfig()
        for name in ("get", "set", "update", "get_all"):
            self.assertFalse(hasattr(config, name), msg=f"FinancialConfig.{name} should not exist")

    def test_reset_to_defaults_discards_scenario(self):
        config = FinancialConfig()
        config.apply_scenario("test", {"tax": {"state": {"tax_rate": 99.0}}})
        self.assertEqual(config.tax.state.tax_rate, 99.0)
        self.assertEqual(config.scenario, "test")

        config.reset_to_defaults()
        self.assertEqual(config.tax.state.tax_rate, 6.0)
        self.assertIsNone(config.scenario)

    def test_resolve_prefers_explicit_config(self):
        explicit = FinancialConfig()
        self.assertIs(resolve_financial_config(explicit), explicit)
        self.assertIs(resolve_financial_config(None), default_financial_config())


class TestFinancialConfig(unittest.TestCase):
    """Test financial configuration"""

    def setUp(self):
        self.config = FinancialConfig()

    def test_default_values(self):
        """Test that default financial values are properly initialized"""
        # Test tax values
        self.assertEqual(self.config.tax.state.tax_rate, 6.0)
        self.assertEqual(self.config.tax.fica.social_security_rate, 6.2)

        # Test retirement values
        self.assertEqual(self.config.retirement.federal_retirement_age, 59.5)
        self.assertEqual(self.config.retirement.ira.contribution_limit, 7500)

        # Test account values
        self.assertEqual(self.config.accounts.bank.compound_rate, 12)

    def test_get_federal_standard_deduction(self):
        """Test getting federal standard deduction"""
        single_deduction = self.config.get_federal_standard_deduction(FilingStatus.SINGLE)
        mfj_deduction = self.config.get_federal_standard_deduction(FilingStatus.MARRIED_FILING_JOINTLY)

        self.assertEqual(single_deduction, 16100)
        self.assertEqual(mfj_deduction, 32200)

    def test_get_federal_tax_brackets(self):
        """Test getting federal tax brackets"""
        single_brackets = self.config.get_federal_tax_brackets(FilingStatus.SINGLE)

        self.assertIsInstance(single_brackets, list)
        self.assertEqual(len(single_brackets), 7)
        self.assertEqual(single_brackets[0], [0, 12400, 10])  # First bracket
        self.assertEqual(single_brackets[-1][2], 37)  # Highest rate

    def test_get_job_401k_contrib_limit(self):
        """Test getting 401k contribution limits"""
        # Under 50
        limit_under_50 = self.config.get_job_401k_contrib_limit(40)
        self.assertEqual(limit_under_50, 24500)

        # 50 and over (catch-up)
        limit_over_50 = self.config.get_job_401k_contrib_limit(55)
        self.assertEqual(limit_over_50, 32500)  # 24500 + 8000

    def test_get_max_tax_rate(self):
        """Test getting maximum tax rate"""
        max_rate = self.config.get_max_tax_rate(FilingStatus.SINGLE)
        self.assertEqual(max_rate, 37.0)

    def test_scenario_override(self):
        """Test scenario-specific configuration overrides"""
        # Test high tax scenario
        high_tax_overrides = {
            "tax": {
                "federal": {
                    "tax_brackets": {
                        "single": [
                            [0, 10000, 15],  # Higher rates
                            [10001, 50000, 25],
                            [50001, float("inf"), 45],
                        ]
                    }
                },
                "state": {
                    "tax_rate": 10.0  # Higher state tax
                },
            }
        }

        self.config.apply_scenario("high_tax", high_tax_overrides)

        # Check that overrides are applied
        self.assertEqual(self.config.tax.state.tax_rate, 10.0)
        brackets = self.config.get_federal_tax_brackets(FilingStatus.SINGLE)
        self.assertEqual(brackets[0][2], 15)  # Higher first bracket rate
        self.assertEqual(self.config.get_max_tax_rate(FilingStatus.SINGLE), 45.0)


class TestGlobalConfigManager(unittest.TestCase):
    """The deprecated global manager is a thin, warning shim over the shared fallback config."""

    def tearDown(self):
        # The shim mutates the shared fallback config; never leak a scenario into other tests.
        default_financial_config().reset_to_defaults()

    def test_singleton_behavior(self):
        """Test that GlobalConfigManager is a singleton"""
        config1 = GlobalConfigManager()
        config2 = GlobalConfigManager()

        self.assertIs(config1, config2)

    def test_financial_access_warns_and_returns_shared_default(self):
        config_manager = GlobalConfigManager()

        with self.assertWarns(DeprecationWarning):
            financial = config_manager.financial
        self.assertIs(financial, default_financial_config())
        self.assertEqual(financial.tax.state.tax_rate, 6.0)

    def test_apply_scenario(self):
        """Test applying scenarios through global manager"""
        config_manager = GlobalConfigManager()

        recession_overrides = {
            "accounts": {
                "bank": {
                    "default_interest_rate": 0.1  # Lower interest rates
                },
                "brokerage": {
                    "default_growth_rate": 3.0  # Lower growth expectations
                },
            }
        }

        with self.assertWarns(DeprecationWarning):
            config_manager.apply_scenario("recession", recession_overrides)

        fallback = default_financial_config()
        self.assertEqual(fallback.scenario, "recession")
        self.assertEqual(fallback.accounts.bank.default_interest_rate, 0.1)
        self.assertEqual(fallback.accounts.brokerage.default_growth_rate, 3.0)

    def test_reset_to_defaults(self):
        """Test resetting to default values"""
        config_manager = GlobalConfigManager()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config_manager.apply_scenario("test", {"tax": {"state": {"tax_rate": 99.0}}})
            self.assertEqual(default_financial_config().tax.state.tax_rate, 99.0)

            config_manager.reset_to_defaults()
            self.assertEqual(default_financial_config().tax.state.tax_rate, 6.0)
            self.assertIsNone(config_manager.get_current_scenario())

    def test_global_scenario_does_not_affect_models(self):
        """Each LifeModel owns its config, so mutating the deprecated global cannot change a model."""
        from ..model import LifeModel

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            GlobalConfigManager().apply_scenario("test", {"tax": {"state": {"tax_rate": 99.0}}})

        self.assertEqual(LifeModel().config.tax.state.tax_rate, 6.0)


class TestConfigurationIntegration(unittest.TestCase):
    """Test integration with existing code"""

    def test_federal_tax_functions_use_config(self):
        """Test that federal tax functions use configuration values"""
        from ..tax.federal import get_federal_standard_deduction, get_federal_tax_brackets

        # These should return the same values as direct config access
        deduction = get_federal_standard_deduction(FilingStatus.SINGLE)
        self.assertEqual(deduction, 16100)

        brackets = get_federal_tax_brackets(FilingStatus.SINGLE)
        self.assertIsInstance(brackets, list)
        self.assertEqual(len(brackets), 7)

    def test_limits_functions_use_config(self):
        """Test that limits functions use configuration values"""
        from ..limits import federal_retirement_age, job_401k_contrib_limit

        # Test 401k limits
        self.assertEqual(job_401k_contrib_limit(40), 24500)
        self.assertEqual(job_401k_contrib_limit(55), 32500)

        # Test retirement age
        self.assertEqual(federal_retirement_age(), 59.5)


class TestPerModelConfig(unittest.TestCase):
    """Two models with different scenarios coexist in one process."""

    def test_scenarios_coexist_with_different_tax_results(self):
        from ..model import LifeModel
        from ..tax.tax import get_income_taxes_due

        model_high = LifeModel(scenario="high_tax")
        model_default = LifeModel()

        # The two models hold independent configs.
        self.assertEqual(model_high.config.tax.state.tax_rate, 10.0)
        self.assertEqual(model_default.config.tax.state.tax_rate, 6.0)

        taxes_high = get_income_taxes_due(100000, 0, FilingStatus.SINGLE, model_high.config)
        taxes_default = get_income_taxes_due(100000, 0, FilingStatus.SINGLE, model_default.config)
        self.assertGreater(taxes_high.total, taxes_default.total)

    def test_explicit_config_object(self):
        from ..model import LifeModel

        cfg = FinancialConfig()
        cfg.apply_scenario("low_tax", {"tax": {"state": {"tax_rate": 1.0}}})
        model = LifeModel(config=cfg)
        self.assertEqual(model.config.tax.state.tax_rate, 1.0)
        # A default model is unaffected.
        self.assertEqual(LifeModel().config.tax.state.tax_rate, 6.0)


class TestScenarioValidation(unittest.TestCase):
    """Scenario overrides are re-validated through Pydantic."""

    def test_misspelled_key_raises(self):
        config = FinancialConfig()
        with self.assertRaises(ValueError):
            config.apply_scenario("bad", {"tax": {"state": {"tax_rate_typo": 5.0}}})

    def test_out_of_range_value_raises(self):
        config = FinancialConfig()
        with self.assertRaises(ValueError):
            config.apply_scenario("bad", {"tax": {"state": {"tax_rate": 150.0}}})

    def test_all_packaged_scenarios_map_to_schema_fields(self):
        from ..config.models import FinancialConfigModel
        from ..config.scenarios import get_scenario, list_scenarios

        for name in list_scenarios():
            overrides = get_scenario(name)
            # Applying re-validates through Pydantic (extra='forbid'), so an unknown
            # key would raise here.
            FinancialConfig().apply_scenario(name, overrides)
            # And every key path corresponds to a validated schema field.
            self._assert_keys_in_model(overrides, FinancialConfigModel, name)

    def _assert_keys_in_model(self, data, model_cls, scenario):
        from pydantic import BaseModel

        for key, value in data.items():
            self.assertIn(
                key, model_cls.model_fields, msg=f"Scenario '{scenario}' key '{key}' not in {model_cls.__name__}"
            )
            annotation = model_cls.model_fields[key].annotation
            if isinstance(value, dict) and isinstance(annotation, type) and issubclass(annotation, BaseModel):
                self._assert_keys_in_model(value, annotation, scenario)


class TestYearIndexedTax(unittest.TestCase):
    """Year-indexed tax parameters and the projection rule."""

    def setUp(self):
        self.config = FinancialConfig()

    def test_published_years(self):
        self.assertEqual(self.config.tax_year(2022).standard_deduction.single, 12950)
        self.assertEqual(self.config.tax_year(2026).standard_deduction.single, 16100)
        self.assertEqual(self.config.tax_year(2026).ss_wage_base, 184500)

    def test_future_year_frozen_at_latest(self):
        projected = self.config.tax_year(2035)
        self.assertEqual(projected.year, 2035)
        self.assertEqual(projected.standard_deduction.single, 16100)  # frozen at 2026

    def test_prior_year_uses_earliest(self):
        projected = self.config.tax_year(2000)
        self.assertEqual(projected.year, 2000)
        self.assertEqual(projected.standard_deduction.single, 12950)  # earliest (2022)


class TestPlan529ConfigFlows(unittest.TestCase):
    """Regression: the accounts.plan_529 block is validated and reaches consumers."""

    def test_plan_529_defaults_present(self):
        config = FinancialConfig()
        self.assertEqual(config.accounts.plan_529.annual_contribution_limit, 19000)
        self.assertEqual(config.accounts.plan_529.qualified_expense_penalty, 10.0)

    def test_plan_529_scenario_override_flows(self):
        config = FinancialConfig()
        config.apply_scenario("edu", {"accounts": {"plan_529": {"annual_contribution_limit": 25000}}})
        self.assertEqual(config.accounts.plan_529.annual_contribution_limit, 25000)


class TestNoImportTimeFileIO(unittest.TestCase):
    """Importing life_model must not read the config YAML."""

    def test_no_config_load_on_import(self):
        import subprocess
        import sys

        code = (
            "import life_model\n"
            "import life_model.config.config_manager\n"
            "from life_model.config import financial_config\n"
            "assert financial_config._default_config is None, 'config loaded at import time'\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)


class TestNoLibraryUseOfGlobalConfig(unittest.TestCase):
    """Library code must read the owning model's config, never the deprecated global shim."""

    def test_no_module_imports_config_manager(self):
        import ast
        from pathlib import Path

        import life_model

        root = Path(life_model.__file__).parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(root)
            if relative.parts[0] == "tests" or relative == Path("config/config_manager.py"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if any(name.endswith("config_manager") for name in names):
                    offenders.append(str(relative))
        self.assertEqual(offenders, [], msg="Use model.config or resolve_financial_config(config) instead")


if __name__ == "__main__":
    unittest.main()
