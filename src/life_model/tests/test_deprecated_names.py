# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""The constructor-name aliases deprecated in 0.4.0 are removed: old names and positional arguments after the
owner raise ``TypeError``, the canonical keyword names build without warnings, and the
``deprecated_arguments`` helper still works for future renames."""

import unittest
import warnings

from .. import deprecated_names
from ..account.bank import BankAccount
from ..account.brokerage import BrokerageAccount
from ..account.hsa import HealthSavingsAccount, HSAType
from ..account.job401k import Job401kAccount
from ..account.pension import Pension
from ..account.roth_IRA import RothIRA
from ..account.traditional_IRA import TraditionalIRA
from ..debt.car_loan import CarLoan
from ..debt.credit_card import CreditCard
from ..debt.student_loan import StudentLoan, StudentLoanType
from ..housing.apartment import Apartment
from ..housing.home import Home, HomeExpenses, Mortgage
from ..insurance.annuity import Annuity, AnnuityType
from ..insurance.general_insurance import Insurance, InsuranceType
from ..insurance.life_insurance import LifeInsurance, LifeInsuranceType
from ..insurance.social_security import SocialSecurity
from ..model import LifeModel
from ..people.family import Family
from ..people.person import Person, Spending
from ..work.job import Job, Salary


class TestRemovedConstructorNames(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2026, end_year=2027)
        self.person = Person(
            family=Family(self.model), name="P", age=40, retirement_age=65, spending=Spending(self.model)
        )
        BankAccount(owner=self.person, company="Bank", balance=1000)

    def test_old_names_and_positional_arguments_raise(self):
        p, m = self.person, self.model
        removed = {
            "BankAccount(interest_rate=)": lambda: BankAccount(owner=p, company="B", interest_rate=1.5),
            "BankAccount positional": lambda: BankAccount(p, "B", "Bank", 100),
            "BrokerageAccount positional": lambda: BrokerageAccount(p, "Broker", 1000, 5),
            "TraditionalIRA(person=, growth_rate=)": lambda: TraditionalIRA(person=p, growth_rate=4),
            "RothIRA(contribution_limit=)": lambda: RothIRA(p, contribution_limit=6000),
            "HSA(contribution_limit=)": lambda: HealthSavingsAccount(
                p, hsa_type=HSAType.INDIVIDUAL, contribution_limit=4000
            ),
            "Job positional": lambda: Job(p, "Co", "Eng", Salary(m, base_annual=1)),
            "Salary(base=)": lambda: Salary(m, base=1),
            "Job401kAccount(pretax_contrib_percent=)": lambda: Job401kAccount(owner=p, pretax_contrib_percent=5),
            "Pension(cola_percent=)": lambda: Pension(p, company="Co", cola_percent=2),
            "CarLoan positional": lambda: CarLoan(p, 20000, 5, 6.0, "Car"),
            "StudentLoan(loan_amount=)": lambda: StudentLoan(
                owner=p, loan_type=StudentLoanType.PRIVATE, loan_amount=1, rate_pct=1, term_years=1
            ),
            "Mortgage(start_date=)": lambda: Mortgage(original_amount=1, start_date=2026, term_years=1, rate_pct=1),
            "CreditCard(yearly_interest_rate=)": lambda: CreditCard(p, card_name="C", yearly_interest_rate=20),
            "HomeExpenses(hoa_amount=)": lambda: HomeExpenses(m, hoa_amount=1200),
            "Home(person=)": lambda: Home(person=p, name="H", purchase_price=1, down_payment=0, mortgage=None),
            "Apartment(monthly_rent=)": lambda: Apartment(p, name="A", monthly_rent=1500),
            "LifeInsurance(monthly_premium=)": lambda: LifeInsurance(
                p, policy_type=LifeInsuranceType.TERM, death_benefit=1, monthly_premium=30
            ),
            "Insurance(annual_premium=)": lambda: Insurance(
                p, insurance_type=InsuranceType.AUTO, company="Co", annual_premium=900
            ),
            "Annuity(interest_rate=)": lambda: Annuity(p, annuity_type=AnnuityType.FIXED, interest_rate=4.0),
            "SocialSecurity(withdrawal_start_age=)": lambda: SocialSecurity(p, withdrawal_start_age=67),
            "Spending(base=, yearly_increase=)": lambda: Spending(m, base=1000, yearly_increase=3),
        }
        for name, build in removed.items():
            with self.subTest(name), self.assertRaises(TypeError):
                build()

    def test_canonical_names_build_without_warnings(self):
        p, m = self.person, self.model
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            BrokerageAccount(p, company="Broker", balance=1000, growth_pct=5)
            TraditionalIRA(p, growth_pct=4, contribution_limit_annual=6000)
            CarLoan(p, original_amount=20000, term_years=5, rate_pct=6.0, name="Car")
            Apartment(p, name="A", rent_monthly=1500, rent_growth_pct=3)
            Spending(m, base_annual=1000, growth_pct=3)

    def test_no_core_constructor_has_deprecated_names(self):
        self.assertEqual(deprecated_names.deprecated_names(), {})


class TestDeprecatedArgumentsHelper(unittest.TestCase):
    """The helper stays for future renames: an old keyword or positional argument maps onto the new name with a
    DeprecationWarning."""

    def setUp(self):
        @deprecated_names.deprecated_arguments({"old": "new"}, positional=("new", "other"))
        def init(self, owner, *, new=0, other=0):
            self.values = (owner, new, other)

        self.cls = type("Renamed", (), {"__init__": init, "__module__": __name__})
        owner = f"{__name__}.{init.__qualname__.rsplit('.', 1)[0]}"
        self.addCleanup(deprecated_names.REGISTRY.pop, owner, None)
        self.addCleanup(deprecated_names.POSITIONAL.pop, owner, None)

    def test_an_old_keyword_maps_to_the_new_one_with_a_warning(self):
        with self.assertWarnsRegex(DeprecationWarning, r"\(old=\) is deprecated; use new="):
            self.assertEqual(self.cls("o", old=3).values, ("o", 3, 0))

    def test_positional_arguments_map_onto_the_former_order_with_a_warning(self):
        with self.assertWarnsRegex(DeprecationWarning, "positional arguments after the first 1"):
            self.assertEqual(self.cls("o", 1, 2).values, ("o", 1, 2))

    def test_both_names_or_too_many_positionals_raise(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            with self.assertRaises(TypeError):
                self.cls("o", old=1, new=2)
            with self.assertRaises(TypeError):
                self.cls("o", 1, 2, 3)


if __name__ == "__main__":
    unittest.main()
