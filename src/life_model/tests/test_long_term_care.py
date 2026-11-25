# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the long-term-care hazard/care-state agent and LTC insurance offset."""

import unittest
from typing import ClassVar

from ..account.bank import BankAccount
from ..healthcare import LongTermCare
from ..insurance.general_insurance import Insurance, InsuranceType
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending


def _flat_model(start_year=2026, end_year=2060, seed=None):
    """A model with zero CPI and zero medical inflation premium so dollar factors are exactly 1."""
    from ..config.financial_config import FinancialConfig

    cfg = FinancialConfig()
    cfg.apply_scenario("flat", {"economy": {"inflation": 0.0}, "healthcare": {"medical_inflation_premium": 0.0}})
    return LifeModel(start_year=start_year, end_year=end_year, seed=seed, config=cfg)


def _make_person(model, age, balance=10_000_000):
    family = Family(model)
    person = Person(family=family, name="P", age=age, retirement_age=90, spending=Spending(model, base_annual=0))
    BankAccount(owner=person, company="Bank", balance=balance)
    return person


def _episode_trace(seed):
    """Run a seeded 40-year sim and return (yearly net LTC costs, episodes started)."""
    model = _flat_model(start_year=2026, end_year=2065, seed=seed)
    person = _make_person(model, age=64)
    ltc = LongTermCare(person)
    costs = []
    for _ in model.get_year_range():
        model.step_year()
        costs.append(ltc.stat_medical_costs)
    return costs, ltc.episodes_started


class TestLongTermCare(unittest.TestCase):
    def test_no_hazard_before_start_age(self):
        """No care episode can start before the configured start age."""
        model = _flat_model()
        person = _make_person(model, age=40)
        ltc = LongTermCare(person)
        self.assertEqual(ltc._annual_hazard(50), 0.0)
        self.assertGreater(ltc._annual_hazard(70), 0.0)

    def test_hazard_increases_with_age(self):
        """The configured hazard bands rise with age."""
        model = _flat_model()
        ltc = LongTermCare(_make_person(model, age=70))
        self.assertLess(ltc._annual_hazard(70), ltc._annual_hazard(80))
        self.assertLess(ltc._annual_hazard(80), ltc._annual_hazard(95))

    def test_seeded_determinism(self):
        """Same seed => identical episode timing and costs; different seed differs eventually."""
        costs_a, episodes_a = _episode_trace(seed=1234)
        costs_b, episodes_b = _episode_trace(seed=1234)
        self.assertEqual(costs_a, costs_b)
        self.assertEqual(episodes_a, episodes_b)

    def test_care_year_charges_annual_cost(self):
        """A forced care year charges the configured annual cost through the bill path."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 3
        model.step_year()
        annual_cost = model.config.healthcare.long_term_care.annual_cost
        self.assertEqual(ltc.stat_medical_costs, annual_cost)
        self.assertEqual(person.stat_money_spent, annual_cost)
        self.assertEqual(ltc.care_years_remaining, 2)
        self.assertTrue(ltc.in_care)

    def test_episode_ends_after_duration(self):
        """The care state clears when the drawn duration is exhausted."""
        model = _flat_model(end_year=2027)
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step_year()
        self.assertFalse(ltc.in_care)

    def test_insurance_offsets_by_exactly_the_benefit_cap(self):
        """LTC insurance reduces the net care cost by exactly the annual benefit (worked example).

        Care cost $111,325; policy benefit $60,000/yr, no deductible => net cost $51,325.
        """
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            owner=person,
            insurance_type=InsuranceType.LONG_TERM_CARE,
            company="CarePlus",
            premium_annual=3000,
            coverage_amount=60000,
            deductible=0,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 2
        model.step_year()
        annual_cost = model.config.healthcare.long_term_care.annual_cost  # 111,325
        self.assertEqual(ltc.stat_medical_costs, annual_cost - 60000)
        # Money spent includes the gross care cost plus the LTC premium (both through bills);
        # the insurance payout arrived in the bank before settlement.
        self.assertEqual(person.stat_money_spent, annual_cost + 3000)

    def test_insurance_with_deductible(self):
        """The deductible reduces the payout: claim capped at the benefit, payout net of deductible."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            owner=person,
            insurance_type=InsuranceType.LONG_TERM_CARE,
            company="CarePlus",
            premium_annual=3000,
            coverage_amount=60000,
            deductible=10000,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step_year()
        annual_cost = model.config.healthcare.long_term_care.annual_cost
        # Claimable capped at coverage = 60,000; payout = 60,000 - 10,000 deductible = 50,000.
        self.assertEqual(ltc.stat_medical_costs, annual_cost - 50000)

    def test_non_ltc_policies_do_not_offset(self):
        """Only LONG_TERM_CARE policies offset care costs."""
        model = _flat_model(end_year=2026)
        person = _make_person(model, age=80)
        Insurance(
            owner=person,
            insurance_type=InsuranceType.HEALTH,
            company="Blue Cross",
            premium_annual=5000,
            coverage_amount=1000000,
            deductible=0,
        )
        ltc = LongTermCare(person)
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step_year()
        self.assertEqual(ltc.stat_medical_costs, model.config.healthcare.long_term_care.annual_cost)

    def test_no_agent_no_effect(self):
        """Without a LongTermCare agent, frames are unchanged (opt-in guarantee)."""

        def run(with_ltc: bool):
            model = _flat_model(start_year=2026, end_year=2056, seed=99)
            person = _make_person(model, age=64)
            if with_ltc:
                LongTermCare(person)
            model.run()
            return model.datacollector.get_model_vars_dataframe()

        self.assertTrue(run(False).equals(run(False)))


def _care_model(overrides=None, start_year=2026, end_year=2026, seed=None):
    """A flat-dollar model (zero CPI and medical premium) with ``healthcare.long_term_care`` overrides.

    No episode starts on its own unless ``overrides`` sets ``hazard_bands``, so a test's scripted
    episodes are the only care in the run.
    """
    from ..config.financial_config import FinancialConfig

    cfg = FinancialConfig()
    overlay = {"economy": {"inflation": 0.0}, "healthcare": {"medical_inflation_premium": 0.0}}
    overlay["healthcare"]["long_term_care"] = {
        "hazard_bands": [{"max_age": 200, "annual_hazard": 0.0}],
        **(overrides or {}),
    }
    cfg.apply_scenario("care", overlay)
    return LifeModel(start_year=start_year, end_year=end_year, seed=seed, config=cfg)


#: Three settings with round costs so the expected dollars are easy to read.
SETTINGS = [
    {"name": "home_care", "annual_cost": 60000, "entry_share": 0.5, "mortality_multiplier": 1.0},
    {"name": "assisted_living", "annual_cost": 72000, "entry_share": 0.25, "mortality_multiplier": 1.5},
    {"name": "nursing_home", "annual_cost": 120000, "entry_share": 0.25, "mortality_multiplier": 3.0},
]


def _ltc_policy(person, **kwargs):
    terms = {"premium_annual": 3000, "coverage_amount": 200000, "deductible": 0, "elimination_months": 0}
    terms.update(kwargs)
    return Insurance(owner=person, insurance_type=InsuranceType.LONG_TERM_CARE, company="CarePlus", **terms)


class TestCareEpisodesByMonth(unittest.TestCase):
    def test_drawn_duration_mean_matches_the_configured_mean(self):
        """Episode lengths are whole months whose mean is the configured mean (no round-up bias)."""
        model = _care_model({"mean_duration_years": 2.3}, seed=5)
        ltc = LongTermCare(_make_person(model, age=80))
        draws = [ltc._draw_episode_months() for _ in range(20000)]
        mean = sum(draws) / len(draws)
        self.assertAlmostEqual(mean, 2.3 * 12, delta=0.03 * 2.3 * 12)
        self.assertGreaterEqual(min(draws), 1)
        self.assertTrue(any(d % 12 for d in draws))

    def test_an_episode_ending_mid_year_charges_only_its_months(self):
        """Five care months left: five twelfths of the annual cost, then the person leaves care."""
        model = _care_model({"settings": SETTINGS})
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.start_episode("nursing_home", months=5)
        model.step_year()
        self.assertAlmostEqual(ltc.stat_medical_costs, 120000 * 5 / 12)
        self.assertFalse(ltc.in_care)

    def test_care_years_remaining_reads_whole_years(self):
        """The legacy ``care_years_remaining`` setter and getter work in years of twelve months."""
        model = _care_model()
        ltc = LongTermCare(_make_person(model, age=80))
        ltc.in_care = True
        ltc.care_years_remaining = 3
        self.assertEqual(ltc.care_months_remaining, 36)
        ltc.care_months_remaining = 13
        self.assertEqual(ltc.care_years_remaining, 2)

    def test_episodes_start_in_any_month(self):
        """The onset draw is monthly: across seeds some episodes begin after January."""
        months = set()
        for seed in range(40):
            model = _care_model(
                {"hazard_bands": [{"max_age": 200, "annual_hazard": 0.5}]}, start_year=2026, end_year=2027, seed=seed
            )
            ltc = LongTermCare(_make_person(model, age=80))
            model.run()
            months.update(month for _, month in ltc.episode_starts)
        self.assertGreater(len(months - {1}), 3)


class TestCareSettings(unittest.TestCase):
    def test_entry_setting_follows_the_entry_shares(self):
        """The setting drawn at onset follows the configured entry shares."""
        model = _care_model({"settings": SETTINGS}, seed=11)
        ltc = LongTermCare(_make_person(model, age=80))
        counts = {"home_care": 0, "assisted_living": 0, "nursing_home": 0}
        for _ in range(8000):
            counts[ltc._draw_setting().name] += 1
        self.assertAlmostEqual(counts["home_care"] / 8000, 0.5, delta=0.03)
        self.assertAlmostEqual(counts["assisted_living"] / 8000, 0.25, delta=0.03)
        self.assertAlmostEqual(counts["nursing_home"] / 8000, 0.25, delta=0.03)

    def test_each_setting_charges_its_own_cost(self):
        for name, cost in (("home_care", 60000), ("assisted_living", 72000), ("nursing_home", 120000)):
            with self.subTest(setting=name):
                model = _care_model({"settings": SETTINGS})
                person = _make_person(model, age=80)
                ltc = LongTermCare(person)
                ltc.start_episode(name, months=24)
                model.step_year()
                self.assertAlmostEqual(ltc.stat_medical_costs, cost)
                self.assertEqual(ltc.setting.name, name)

    def test_a_setting_without_a_cost_uses_the_annual_cost(self):
        """A setting with no annual_cost of its own (the default nursing home) costs ``annual_cost``."""
        settings = [dict(SETTINGS[0]), {"name": "nursing_home", "entry_share": 0.5}]
        model = _care_model({"settings": settings, "annual_cost": 99000})
        person = _make_person(model, age=80)
        ltc = LongTermCare(person)
        ltc.start_episode("nursing_home", months=12)
        model.step_year()
        self.assertAlmostEqual(ltc.stat_medical_costs, 99000)

    def test_forced_care_without_a_setting_is_the_nursing_home(self):
        """Setting ``in_care`` directly (no drawn setting) is priced as the nursing home."""
        model = _care_model({"settings": SETTINGS})
        ltc = LongTermCare(_make_person(model, age=80))
        ltc.in_care = True
        ltc.care_years_remaining = 1
        model.step_year()
        self.assertAlmostEqual(ltc.stat_medical_costs, 120000)

    def test_entry_shares_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            _care_model({"settings": [dict(SETTINGS[0], entry_share=0.4), dict(SETTINGS[2], entry_share=0.4)]})

    def test_care_raises_the_mortality_hazard_by_the_setting_multiplier(self):
        """In care, the annual death probability q becomes 1 - (1 - q)^m (a hazard ratio of m)."""
        from ..people.types import GenderAtBirth, MortalityMode

        model = _care_model({"settings": SETTINGS})
        family = Family(model)
        person = Person(
            family=family,
            name="P",
            age=85,
            retirement_age=65,
            spending=Spending(model, base_annual=0),
            gender=GenderAtBirth.FEMALE,
            mortality_mode=MortalityMode.STOCHASTIC,
        )
        ltc = LongTermCare(person)
        base = person.annual_mortality_chance()
        ltc.start_episode("assisted_living", months=12)
        self.assertAlmostEqual(person.annual_mortality_chance(), 1 - (1 - base) ** 1.5)
        ltc.start_episode("nursing_home", months=12)
        self.assertAlmostEqual(person.annual_mortality_chance(), 1 - (1 - base) ** 3.0)


class TestLongTermCareInsuranceTerms(unittest.TestCase):
    def _care_year(self, policy_terms, months=12, years=1, setting="nursing_home"):
        model = _care_model({"settings": SETTINGS}, end_year=2026 + years - 1)
        person = _make_person(model, age=80)
        policy = _ltc_policy(person, **policy_terms)
        ltc = LongTermCare(person)
        ltc.start_episode(setting, months=months)
        return model, person, policy, ltc

    def test_elimination_period_delays_benefits(self):
        """A 3-month elimination period: the first three care months are not reimbursed."""
        model, _, policy, ltc = self._care_year({"elimination_months": 3})
        model.step_year()
        self.assertAlmostEqual(policy.stat_claims_paid_out, 120000 * 9 / 12)
        self.assertAlmostEqual(ltc.stat_medical_costs, 120000 * 3 / 12)

    def test_elimination_period_is_met_once(self):
        """The elimination period is satisfied once: a second care year is reimbursed in full."""
        model, _, policy, _ = self._care_year({"elimination_months": 3}, months=24, years=2)
        model.step_year()
        paid_first = policy.stat_claims_paid_out
        model.step_year()
        self.assertAlmostEqual(policy.stat_claims_paid_out - paid_first, 120000)

    def test_inflation_rider_grows_the_benefit(self):
        """A 5% compound rider: the third year's benefit is 1.05^2 times the issued benefit."""
        model, _, policy, _ = self._care_year({"coverage_amount": 50000, "benefit_growth_pct": 5}, months=36, years=3)
        paid = []
        for _ in range(3):
            before = policy.stat_claims_paid_out
            model.step_year()
            paid.append(policy.stat_claims_paid_out - before)
        self.assertAlmostEqual(paid[0], 50000)
        self.assertAlmostEqual(paid[1], 52500)
        self.assertAlmostEqual(paid[2], 55125)

    def test_lifetime_maximum_caps_total_benefits(self):
        """A $150,000 lifetime pool at $100,000 a year: $100,000, then $50,000, then nothing."""
        model, _, policy, _ = self._care_year(
            {"coverage_amount": 100000, "lifetime_benefit_max": 150000}, months=36, years=3
        )
        paid = []
        for _ in range(3):
            before = policy.stat_claims_paid_out
            model.step_year()
            paid.append(policy.stat_claims_paid_out - before)
        self.assertEqual([round(x) for x in paid], [100000, 50000, 0])

    def test_premium_is_waived_while_benefits_are_paid(self):
        """In care past the elimination period at the year start: no premium that year."""
        model, _, policy, _ = self._care_year({"elimination_months": 0}, months=36, years=2)
        model.step_year()
        self.assertEqual(policy.stat_premiums_paid, 0.0)

    def test_premium_waiver_can_be_turned_off(self):
        model, _, policy, _ = self._care_year({"waive_premium_in_claim": False}, months=36, years=1)
        model.step_year()
        self.assertEqual(policy.stat_premiums_paid, 3000)

    def test_death_in_care_still_claims_the_year(self):
        """Dying in July in care: January-June's care is claimed before the estate settles (July's charge
        dies unpaid with the person's bills and is not claimed)."""
        from ..people.types import MortalityMode

        model = _care_model({"settings": SETTINGS}, end_year=2026)
        family = Family(model)
        person = Person(
            family=family,
            name="P",
            age=80,
            retirement_age=65,
            spending=Spending(model, base_annual=0),
            mortality_mode=MortalityMode.FIXED_AGE,
            death_age=81,
            birth="1945-07",
        )
        BankAccount(owner=person, company="Bank", balance=1_000_000)
        policy = _ltc_policy(person)
        ltc = LongTermCare(person)
        ltc.start_episode("nursing_home", months=36)
        model.step_year()
        self.assertTrue(person.is_deceased)
        self.assertAlmostEqual(ltc._gross_charged_total, 120000 * 6 / 12)
        self.assertAlmostEqual(policy.stat_claims_paid_out, 120000 * 6 / 12)


class TestMedicaidLongTermCare(unittest.TestCase):
    MEDICAID: ClassVar[dict] = {
        "asset_limit": 2000,
        "community_spouse_resource_allowance": 150000,
        "minimum_monthly_maintenance_needs_allowance": 2500,
        "personal_needs_allowance_monthly": 50,
    }

    def _model(self, **kw):
        return _care_model({"settings": SETTINGS, "medicaid": self.MEDICAID}, **kw)

    def test_medicaid_pays_once_assets_are_spent_down(self):
        """A single person with $1,000 and no income: Medicaid pays the whole care cost."""
        model = self._model()
        person = _make_person(model, age=80, balance=1000)
        ltc = LongTermCare(person, medicaid=True)
        ltc.start_episode("nursing_home", months=12)
        model.step_year()
        self.assertAlmostEqual(ltc.stat_medical_costs, 0.0)
        self.assertAlmostEqual(ltc.medicaid_paid_this_year, 120000)
        self.assertAlmostEqual(person.debt, 0.0)

    def test_without_medicaid_the_unpaid_cost_is_debt(self):
        model = self._model()
        person = _make_person(model, age=80, balance=1000)
        ltc = LongTermCare(person)
        ltc.start_episode("nursing_home", months=12)
        model.step_year()
        self.assertGreater(person.debt, 100000)
        self.assertEqual(ltc.medicaid_paid_this_year, 0.0)

    def test_assets_above_the_limit_are_spent_first(self):
        """$50,000 in the bank: the person pays until the bank is under the limit, then Medicaid pays."""
        model = self._model()
        person = _make_person(model, age=80, balance=50000)
        ltc = LongTermCare(person, medicaid=True)
        ltc.start_episode("nursing_home", months=12)
        model.step_year()
        paid_by_person = ltc.stat_medical_costs
        self.assertGreaterEqual(paid_by_person, 48000)
        self.assertLess(paid_by_person, 60000)
        self.assertAlmostEqual(paid_by_person + ltc.medicaid_paid_this_year, 120000)
        self.assertAlmostEqual(person.debt, 0.0)

    def test_patient_pays_income_above_the_personal_needs_allowance(self):
        """Eligible with $1,500 a month of income: the person pays $1,450 a month toward care."""
        model = self._model()
        ltc = LongTermCare(_make_person(model, age=80, balance=1000), medicaid=True)
        self.assertAlmostEqual(ltc.patient_pay(10000, monthly_income=1500, spouse_monthly_income=None), 1450)
        self.assertAlmostEqual(ltc.patient_pay(1000, monthly_income=1500, spouse_monthly_income=None), 1000)

    def test_community_spouse_keeps_income_up_to_the_allowance(self):
        """A spouse at home with $1,000 of income keeps $1,500 of the patient's income (up to $2,500)."""
        model = self._model()
        ltc = LongTermCare(_make_person(model, age=80, balance=1000), medicaid=True)
        self.assertAlmostEqual(ltc.patient_pay(10000, monthly_income=3000, spouse_monthly_income=1000), 1450)

    def test_community_spouse_resource_allowance(self):
        """A married couple qualifies while their combined assets are under the limit plus the allowance."""
        model = self._model()
        family = Family(model)
        a = Person(family=family, name="A", age=80, retirement_age=65, spending=Spending(model, base_annual=0))
        b = Person(family=family, name="B", age=78, retirement_age=65, spending=Spending(model, base_annual=0))
        a.get_married(b)
        BankAccount(owner=a, company="Bank", balance=1000)
        BankAccount(owner=b, company="Bank", balance=140000)
        ltc = LongTermCare(a, medicaid=True)
        self.assertTrue(ltc.medicaid_eligible())
        BankAccount(owner=b, company="Bank 2", balance=20000)
        self.assertFalse(ltc.medicaid_eligible())


if __name__ == "__main__":
    unittest.main()
