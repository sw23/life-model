# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import TYPE_CHECKING, List, Optional

from ..account.job401k import Job401kAccount
from ..limits import federal_retirement_age
from ..model import Event, LifeModel, LifeModelAgent
from ..services.debt_service import DebtService
from ..services.payment_service import PaymentService
from ..services.tax_calculation_service import TaxCalculationService
from ..tax.federal import FilingStatus, get_federal_standard_deduction
from ..tax.income import IncomeLedger, IncomeType
from ..tax.state import state_income_tax_for_unit
from ..tax.tax import TaxesDue, compute_taxes
from .family import Family
from .mortality import get_blended_chance_of_mortality, get_chance_of_mortality
from .types import GenderAtBirth, MortalityMode  # noqa: F401  (re-exported for backward compatibility)

if TYPE_CHECKING:
    from ..dependents.child import Child
    from ..insurance.social_security import SocialSecurity


class Person(LifeModelAgent):
    # Age first in pre_step so income/RMD calculations see the current-year age.
    STEP_PRIORITY = {"pre_step": -20}

    def __init__(
        self,
        family: Family,
        name: str,
        age: int,
        retirement_age: float,
        spending: "Spending",
        *,
        gender: GenderAtBirth = GenderAtBirth.OTHER,
        mortality_mode: MortalityMode = MortalityMode.IMMORTAL,
        death_age: Optional[int] = None,
        state: Optional[str] = None,
    ):
        """Person

        Args:
            family (Family): Family of which the person is a part.
            name (str): Person's name.
            age (int): Person's age.
            retirement_age (float): Person's retirement age.
            spending (Spending): Person's spending habits.
            gender (GenderAtBirth, optional): Gender at birth, used for the mortality table. Defaults
                to ``OTHER``, which draws against a male/female blended rate.
            mortality_mode (MortalityMode, optional): How death is determined each year. Defaults to
                ``IMMORTAL`` (the person never dies) so existing simulations stay deterministic.
            death_age (int, optional): Age of death when ``mortality_mode`` is ``FIXED_AGE``.
            state (str, optional): Two-letter state of residence for state income tax. Defaults to
                ``None``, which falls back to ``config.tax.state.default_state`` (Plan 17 D2). A
                single state applies to the whole tax unit (no part-year/multi-state).
        """
        super().__init__(family.model)
        self.family = family
        self.name = name
        self.age = age
        self.retirement_age = retirement_age
        self.spending = spending
        self.state = state
        self.gender = gender
        self.mortality_mode = mortality_mode
        self.death_age = death_age
        self.is_deceased = False
        # Optional explicit estate beneficiary (a Person). When unset, the estate passes to the
        # surviving spouse, then to the first surviving family member.
        self.estate_beneficiary: Optional["Person"] = None
        # Unified estate-tax exemption consumed during life by taxable gifts (e.g. irrevocable
        # trust funding above the annual gift exclusion). Reduces the exemption at death.
        self.estate_exemption_used = 0.0
        # Year this person was widowed (used to switch filing status to SINGLE the following year).
        self._widowed_year: Optional[int] = None
        self.debt = 0
        # Per-person income ledger: separates FICA wages from ordinary taxable income so that
        # payroll tax and income tax each see the correct base (see tax/income.py).
        self.income = IncomeLedger()
        self.spouse = None
        self.filing_status = FilingStatus.SINGLE
        self.social_security: Optional[SocialSecurity] = None
        self.retirement_triggered = False
        self._retirement_age_event_logged = False
        # Cash held when the person has no bank account (see receive_cash).
        self.cash = 0.0
        self._warned_no_bank_account = False

        self.stat_money_spent = 0.0
        self.stat_taxes_paid = 0.0
        self.stat_bank_balance = 0.0
        self.stat_housing_costs = 0.0
        self.stat_interest_paid = 0.0
        self.stat_ss_income = 0.0

        # Initialize services for business logic
        self.tax_service = TaxCalculationService(self)
        self.payment_service = PaymentService(self)
        self.debt_service = DebtService(self)

        self.family.members.append(self)

    @property
    def jobs(self):
        """Get all jobs for this person from the registry"""
        return self.model.registries.jobs.get_items(self)

    @property
    def bank_accounts(self):
        """Get all bank accounts for this person from the registry"""
        return self.model.registries.bank_accounts.get_items(self)

    @property
    def homes(self):
        """Get all homes for this person from the registry"""
        return self.model.registries.homes.get_items(self)

    @property
    def apartments(self):
        """Get all apartments for this person from the registry"""
        return self.model.registries.apartments.get_items(self)

    @property
    def life_insurance_policies(self):
        """Get all life insurance policies for this person from the registry"""
        return self.model.registries.life_insurance_policies.get_items(self)

    @property
    def plan_529s(self):
        """Get all 529 plans for this person from the registry"""
        return self.model.registries.plan_529s.get_items(self)

    @property
    def children(self):
        """Get all child dependents for this person from the registry"""
        return self.model.registries.children.get_items(self)

    @property
    def donations(self):
        """Get all donations for this person from the registry"""
        return self.model.registries.donations.get_items(self)

    @property
    def donor_advised_funds(self):
        """Get all donor advised funds for this person from the registry"""
        return self.model.registries.donor_advised_funds.get_items(self)

    @property
    def pensions(self):
        """Get all pensions for this person from the registry"""
        return self.model.registries.pensions.get_items(self)

    @property
    def trusts(self):
        """Get all trusts for which this person is the grantor, from the registry"""
        return self.model.registries.trusts.get_items(self)

    @property
    def car_loans(self):
        """Get all car loans for this person from the registry"""
        return self.model.registries.car_loans.get_items(self)

    @property
    def credit_cards(self):
        """Get all credit cards (revolving debt) for this person from the registry"""
        return self.model.registries.credit_cards.get_items(self)

    @property
    def student_loans(self):
        """Get all student loans for this person from the registry"""
        return self.model.registries.student_loans.get_items(self)

    @property
    def all_debts(self):
        """All personal debts serviced by the simulation (car loans, credit cards, student loans).

        Mortgages are serviced through the owning ``Home`` and are not included here.
        """
        return [*self.car_loans, *self.credit_cards, *self.student_loans]

    @property
    def outstanding_debt_balance(self) -> float:
        """Total outstanding principal/balance across all serviced personal debts and mortgages.

        Used for net-worth / debt statistics so registered debts are visible (not just the
        unpaid-bills ``debt`` carryover).
        """
        total = sum(d.principal for d in self.all_debts)
        total += sum(home.mortgage.principal for home in self.homes if home.mortgage is not None)
        return total

    @property
    def charitable_deductions(self) -> float:
        """Calculate total charitable deductions for the year

        Includes:
        - Direct donations (deductible at time of donation)
        - DAF contributions (deductible at time of contribution, not distribution)
        """
        # Sum deductions from direct donations
        donation_deductions = sum(d.get_tax_deduction_amount() for d in self.donations)

        # Sum deductions from DAF contributions (tracked in stat_contributions_this_year)
        # DAF contributions are deductible when contributed, not when distributed
        daf_contribution_deductions = sum(daf.stat_contributions_this_year for daf in self.donor_advised_funds)

        return donation_deductions + daf_contribution_deductions

    def itemized_deductions(self, state_income_tax_paid: float = 0.0) -> float:
        """Calculate total itemized deductions.

        Includes:
        - Charitable contributions
        - Mortgage interest (capped to the first $750k of acquisition debt, TCJA)
        - State and local taxes: property tax plus ``state_income_tax_paid``, capped at the SALT
          limit (Plan 17 D4). ``state_income_tax_paid`` defaults to 0 so the property-only result
          is unchanged for every caller that does not thread state income tax.

        TODO: Add other itemized deductions (medical expenses, etc.)
        """
        itemized = self.charitable_deductions

        federal = self.model.config.tax.federal
        salt_paid = state_income_tax_paid
        for home in self.homes:
            mortgage = getattr(home, "mortgage", None)
            if mortgage:
                # Deduct the interest actually paid this year (pre-payment principal), limited to
                # the share attributable to the first $750k of acquisition debt.
                interest = mortgage.interest_paid_this_year
                acquisition_debt = mortgage.loan_amount
                debt_limit = federal.mortgage_interest_debt_limit
                if acquisition_debt > debt_limit:
                    interest *= debt_limit / acquisition_debt
                itemized += interest
            salt_paid += home.property_tax_for_year

        # SALT deduction (property tax + state income tax) is capped.
        itemized += min(salt_paid, federal.salt_deduction_cap)

        return itemized

    @property
    def total_itemized_deductions(self) -> float:
        """Itemized deductions excluding state income tax (property-only SALT)."""
        return self.itemized_deductions()

    def federal_deductions_with_state_tax(self, state_income_tax_paid: float) -> float:
        """Greater of the standard deduction or itemized deductions including state income tax in SALT."""
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.model.config)
        return max(standard_deduction, self.itemized_deductions(state_income_tax_paid))

    @property
    def federal_deductions(self) -> float:
        """Get federal deductions - use greater of standard or itemized (property-only SALT)"""
        standard_deduction = get_federal_standard_deduction(self.filing_status, self.model.config)
        itemized_deductions = self.total_itemized_deductions
        return max(standard_deduction, itemized_deductions)

    @property
    def all_retirement_accounts(self) -> List[Job401kAccount]:
        return [x.retirement_account for x in self.jobs if x.retirement_account is not None]

    @property
    def is_retired(self) -> bool:
        """Check if person is retired"""
        return self.age >= self.retirement_age

    def _repr_html_(self):
        desc = self.name
        desc += "<ul>"
        desc += f"<li>Age: {self.age}</li>"
        desc += f"<li>Retirement Age: {self.retirement_age}</li>"
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.jobs)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.bank_accounts)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.homes)
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.apartments)
        desc += f"<li>Debt: {self.debt}</li>"
        desc += "</ul>"
        return desc

    @property
    def bank_account_balance(self) -> float:
        return sum(x.balance for x in self.bank_accounts)

    @property
    def taxable_income(self) -> float:
        """Ordinary taxable income accumulated this year (income tax base)."""
        return self.income.ordinary_taxable

    @property
    def fica_wages(self) -> float:
        """Earned income subject to FICA this year (payroll tax base)."""
        return self.income.fica_wages

    @staticmethod
    def _withdraw_sequence(withdrawers, amount: float) -> float:
        """Withdraw ``amount`` from a sequence of withdraw callables, in order.

        Each callable takes the remaining amount and returns how much it withdrew.

        Returns:
            float: The shortfall (amount that could not be withdrawn).
        """
        remaining = amount
        for withdraw in withdrawers:
            if remaining <= 0:
                break
            remaining -= withdraw(remaining)
        return remaining

    def deduct_from_bank_accounts(self, amount: float) -> float:
        """Deducts money from bank accounts.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.withdraw for account in self.bank_accounts), amount)

    def deduct_from_pretax_401ks(self, amount: float) -> float:
        """Deducts money from pre-tax 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.deduct_pretax for account in self.all_retirement_accounts), amount)

    def deduct_from_roth_401ks(self, amount: float) -> float:
        """Deducts money from roth 401ks.

        Args:
            amount (float): Amount to deduct.

        Returns:
            float: Amount that could not be deducted.
        """
        return self._withdraw_sequence((account.deduct_roth for account in self.all_retirement_accounts), amount)

    def withdraw_from_pretax_401ks(self, amount: float) -> float:
        """Withdraws money from pre-tax 401ks into the bank account.

        The amount actually withdrawn is added to taxable income and deposited into the bank.

        Args:
            amount (float): Amount to withdraw.

        Returns:
            float: Amount actually withdrawn (may be less than requested if funds are short).
        """
        withdrawn = amount - self.deduct_from_pretax_401ks(amount)
        # Pre-tax 401k distributions are ordinary income but are NOT FICA wages.
        self.income.add(IncomeType.PRETAX_DISTRIBUTION, withdrawn)
        self.receive_cash(withdrawn)
        return withdrawn

    # ------------------------------------------------------------------
    # Person-level withdrawal helpers (Plan 18 D1).
    #
    # Each helper mirrors withdraw_from_pretax_401ks: it moves money from the account type into
    # the bank and records the correct income-ledger entry, so the withdrawal is taxed when the
    # tax unit settles the year inside model.step(). Taxes therefore bite at year-end settlement,
    # not at the moment of withdrawal — that is the simulator's actual semantics.
    #
    # Early-withdrawal penalties are intentionally NOT applied here; they remain the caller's
    # concern until the core penalty backlog item lands.
    # ------------------------------------------------------------------

    def _owned_accounts_of_type(self, account_cls) -> List:
        """This person's accounts of ``account_cls``, discovered by scanning the model's agents
        (IRA/HSA/brokerage accounts reference ``person`` directly and are not registry-backed)."""
        return [a for a in self.model.agents if isinstance(a, account_cls) and getattr(a, "person", None) is self]

    @property
    def traditional_iras(self):
        """Get all Traditional IRA accounts for this person."""
        from ..account.traditional_IRA import TraditionalIRA

        return self._owned_accounts_of_type(TraditionalIRA)

    @property
    def roth_iras(self):
        """Get all Roth IRA accounts for this person."""
        from ..account.roth_IRA import RothIRA

        return self._owned_accounts_of_type(RothIRA)

    @property
    def hsas(self):
        """Get all Health Savings Accounts for this person."""
        from ..account.hsa import HealthSavingsAccount

        return self._owned_accounts_of_type(HealthSavingsAccount)

    @property
    def brokerage_accounts(self):
        """Get all brokerage accounts for this person."""
        from ..account.brokerage import BrokerageAccount

        return self._owned_accounts_of_type(BrokerageAccount)

    def withdraw_from_roth_401ks(self, amount: float) -> float:
        """Withdraws money from Roth 401ks into the bank account.

        Qualified Roth distributions are tax-free, so no income-ledger entry is created
        (taxation of non-qualified Roth *earnings* is a documented simplification).

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn = amount - self.deduct_from_roth_401ks(amount)
        self.receive_cash(withdrawn)
        return withdrawn

    def withdraw_from_traditional_iras(self, amount: float) -> float:
        """Withdraws money from Traditional IRAs into the bank account.

        Traditional IRA distributions are ordinary income (no FICA), exactly like pre-tax 401k
        distributions; the ledger entry is settled by the tax unit at year end.

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn = amount - self._withdraw_sequence((acct.withdraw for acct in self.traditional_iras), amount)
        self.income.add(IncomeType.PRETAX_DISTRIBUTION, withdrawn)
        self.receive_cash(withdrawn)
        return withdrawn

    def withdraw_from_roth_iras(self, amount: float) -> float:
        """Withdraws money from Roth IRAs into the bank account (tax-free distribution).

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn = amount - self._withdraw_sequence((acct.withdraw for acct in self.roth_iras), amount)
        self.receive_cash(withdrawn)
        return withdrawn

    def withdraw_from_hsas(self, amount: float) -> float:
        """Withdraws money from HSAs into the bank account.

        Modeled as a qualified-medical (tax-free) distribution; taxing non-medical HSA
        withdrawals is a documented simplification pending the core penalty backlog item.

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn = amount - self._withdraw_sequence((acct.withdraw for acct in self.hsas), amount)
        self.receive_cash(withdrawn)
        return withdrawn

    def withdraw_from_brokerage_accounts(self, amount: float) -> float:
        """Withdraws money from brokerage accounts into the bank account.

        Capital-gains taxation on the sale is not modeled (documented simplification); the
        withdrawal itself is a nontaxable transfer of principal.

        Returns:
            float: Amount actually withdrawn.
        """
        withdrawn = amount - self._withdraw_sequence((acct.withdraw for acct in self.brokerage_accounts), amount)
        self.receive_cash(withdrawn)
        return withdrawn

    def receive_cash(self, amount: float, source: str = "income"):
        """Receive cash into the person's primary bank account.

        If the person has no bank account, the cash is held in an untracked ``cash`` bucket and a
        warning event is logged once, rather than raising mid-simulation.

        Args:
            amount (float): Amount of cash received.
            source (str, optional): Description of where the cash came from (for the warning event).
        """
        if amount <= 0:
            return
        if self.bank_accounts:
            self.bank_accounts[0].balance += amount
        else:
            self.cash += amount
            if not self._warned_no_bank_account:
                self.model.event_log.add(
                    Event(f"{self.name} received ${amount:,.0f} from {source} but has no bank account; holding as cash")
                )
                self._warned_no_bank_account = True

    def deposit_into_bank_account(self, amount: float):
        """Deposits money into the primary bank account (see receive_cash).

        Args:
            amount (float): Amount to deposit.
        """
        self.receive_cash(amount)

    def pay_bills(self, spending_balance: float) -> float:
        """Pays bills using payment service for optimal prioritization.

        Args:
            spending_balance (float): Amount of money spent.

        Returns:
            float: Amount that could not be paid.
        """
        return self.payment_service.pay_bills_with_prioritization(spending_balance)

    def get_income_taxes_due(self, additional_income: float = 0) -> TaxesDue:
        """Gets income taxes due for the year for this person as a single filer.

        FICA is computed on the person's own wages only; ``additional_income`` (e.g. a prospective
        pre-tax 401k withdrawal) is ordinary income but not FICA wages.

        Args:
            additional_income (float, optional): Additional ordinary income not present in the ledger.

        Returns:
            TaxesDue: Taxes due, split by type.
        """
        ordinary_income = self.taxable_income + additional_income
        # State income tax from the state pack. Computed against the property-only AGI base so it
        # does not depend on itself being in SALT; then folded into SALT for the federal base (D4).
        totals = self.income.totals_by_type()
        totals[IncomeType.PRETAX_DISTRIBUTION] = totals.get(IncomeType.PRETAX_DISTRIBUTION, 0.0) + additional_income
        legacy_agi = max(ordinary_income - self.federal_deductions, 0)
        state_tax = state_income_tax_for_unit(
            totals, self.filing_status, self.state, legacy_agi, self.model.config
        )
        deductions = self.federal_deductions_with_state_tax(state_tax)
        return compute_taxes(
            ordinary_income, deductions, self.filing_status, [self.fica_wages], self.model.config, state_tax=state_tax
        )

    def get_married(self, spouse: "Person", link_spouse: bool = True):
        """Get married.

        Args:
            spouse (Person): Spouse to get married to.
            link_spouse (bool, optional): Whether to call get_married on the spouse object as well. Defaults to True.
        """
        self.spouse = spouse
        self.filing_status = FilingStatus.MARRIED_FILING_JOINTLY
        if link_spouse:
            # Merge the spouse's family into this person's family so the couple settles as a
            # single joint tax unit (previously each spouse could sit in a separate family and
            # each compute a full MFJ tax on half the income).
            if spouse.family is not self.family:
                vacated_family = spouse.family
                for member in list(vacated_family.members):
                    member.family = self.family
                    if member not in self.family.members:
                        self.family.members.append(member)
                vacated_family.members = []
            spouse.get_married(self, False)
            event_str = f"{self.name} and {spouse.name} got married at age {self.age} and {spouse.age}"
            self.model.event_log.add(Event(event_str))

    def add_child(self, name: str, birth_year: Optional[int] = None) -> "Child":
        """Add a child dependent to this person.

        Scheduled births are just ``LifeEvent(year, "Birth of X", person.add_child, "X")``.

        Args:
            name (str): The child's name.
            birth_year (int, optional): Year the child was born. Defaults to the current model year.

        Returns:
            Child: The newly created child (registered on this person).
        """
        from ..dependents.child import Child

        if birth_year is None:
            birth_year = self.model.year
        return Child(self, name, birth_year)

    def get_year_at_age(self, age: int) -> int:
        """Gets the year at a given age.

        Args:
            age (int): Age of the person.

        Returns:
            int: Year at the given age.
        """
        return self.model.year + (age - self.age)

    def pre_step(self):
        if self.is_deceased:
            return
        self.age += 1
        # A surviving spouse files jointly for the year of the death, then switches to single the
        # following year (qualifying-widow treatment is a documented simplification, not modeled).
        if self._widowed_year is not None and self.model.year > self._widowed_year:
            self.filing_status = FilingStatus.SINGLE
            self._widowed_year = None
        self._check_mortality()

    def _check_mortality(self):
        """Determine whether the person dies this year and, if so, orchestrate the death."""
        if self.mortality_mode == MortalityMode.IMMORTAL:
            return
        if self.mortality_mode == MortalityMode.FIXED_AGE:
            if self.death_age is not None and self.age >= self.death_age:
                self.die()
        elif self.mortality_mode == MortalityMode.STOCHASTIC:
            if self.gender == GenderAtBirth.OTHER:
                chance = get_blended_chance_of_mortality(self.age)
            else:
                chance = get_chance_of_mortality(self.age, self.gender)
            # Draw against the model RNG so seeded runs are reproducible.
            if self.model.random.random() <= chance:
                self.die()

    def step(self):
        # Year-end settlement (taxes, spending, housing, one-time expenses, debt) is performed
        # at the tax-unit level in Family.step. Here the person only handles retirement.
        #
        # Retirement uses crossing detection (>=, fired once) so that a non-integer retirement
        # age still triggers and a person can't draw a full salary while "retired".
        if not self.retirement_triggered and self.age >= self.retirement_age:
            for job in self.jobs:
                job.retire()
            self.retirement_triggered = True

        if not self._retirement_age_event_logged and self.age >= int(federal_retirement_age()):
            self.model.event_log.add(Event(f"{self.name} reached retirement age (age {federal_retirement_age()})"))
            self._retirement_age_event_logged = True

    def die(self):
        """Orchestrate the person's death for the current year.

        Executes, in order: stop earned income, pay out life-insurance death benefits, settle
        annuities by payout type, transfer the estate to the inheritor (spouse first), apply
        survivor adjustments, and remove the deceased (and their emptied accounts) from the
        simulation so nothing of theirs steps again.

        Simplifications (documented, backlog for later refinement):
          * Non-spouse inherited pre-tax accounts follow ``estate.inherited_pretax_mode``: the
            SECURE Act 10-year even spread (default) or the legacy death-year lump sum.
          * A widowed spouse files jointly in the death year and single thereafter (no
            qualifying-widow years).
          * Pensions with a survivor election continue a reduced stream to a surviving spouse;
            single-life pensions and life-only annuities simply stop; no state estate taxes.
        """
        if self.is_deceased:
            return
        self.is_deceased = True
        self.model.event_log.add(Event(f"{self.name} died at age {self.age}"))

        # 1. Earned income stops immediately (jobs retire).
        for job in list(self.jobs):
            job.retire()

        # Determine who inherits before moving any money.
        spouse = self.spouse if (self.spouse is not None and not self.spouse.is_deceased) else None
        inheritor = spouse if spouse is not None else self._find_beneficiary()

        # 2. Life-insurance death benefits pay out to the beneficiary; policies then close.
        for policy in list(self.life_insurance_policies):
            policy.process_death_benefit()
            policy.is_active = False

        # 3. Settle annuities: life-only stops; period-certain (with payments left) and
        #    joint-and-survivor continue to the inheritor.
        self._settle_annuities_on_death(inheritor)

        # 3b. Settle pensions: a survivor election continues a reduced stream to a surviving
        #     spouse; otherwise the pension terminates. Done BEFORE the estate transfer (so the
        #     generic registry reassignment doesn't move pensions) and before the Benefit sweep in
        #     _remove_from_simulation (which would otherwise delete the survivor's continued stream).
        self._settle_pensions_on_death(spouse)

        # 4/5. Transfer the estate and adjust the survivor.
        if inheritor is not None:
            self._transfer_estate(inheritor, is_spouse=inheritor is spouse)
        else:
            self.model.event_log.add(Event(f"{self.name}'s estate had no beneficiary; assets dissolved"))

        # 5b. Trusts settle outside the will: a revocable trust pays out directly to its own
        #     beneficiaries (its balance was already counted in the gross estate above), escheating
        #     to the residual inheritor if no beneficiary survives; an irrevocable trust survives
        #     with its own registry entry and keeps growing.
        self._settle_trusts_on_death(inheritor)

        if spouse is not None:
            self._apply_survivor_adjustments(spouse)

        # 6. Remove the deceased (and any now-empty owned agents) from the simulation.
        self._remove_from_simulation()

    def _find_beneficiary(self) -> Optional["Person"]:
        """Non-spouse beneficiary: an explicit designation, else the first surviving family member."""
        if self.estate_beneficiary is not None and not self.estate_beneficiary.is_deceased:
            return self.estate_beneficiary
        for member in self.family.members:
            if member is not self and not member.is_deceased:
                return member
        return None

    def _settle_annuities_on_death(self, inheritor: Optional["Person"]):
        from ..insurance.annuity import AnnuityPayoutType

        for annuity in list(self.model.registries.annuities.get_items(self)):
            continues = annuity.payout_type == AnnuityPayoutType.JOINT_AND_SURVIVOR or (
                annuity.payout_type == AnnuityPayoutType.LIFE_WITH_PERIOD_CERTAIN
                and getattr(annuity, "remaining_period_certain_payments", 0) > 0
            )
            if not (continues and inheritor is not None):
                # Life-only, or no beneficiary to continue payments: the annuity stops.
                annuity.is_active = False

    def _settle_pensions_on_death(self, spouse: Optional["Person"]):
        """Continue survivor pensions to a surviving spouse; terminate the rest.

        A pension with ``survivor_percent > 0`` and a surviving spouse transfers to that spouse at
        ``benefit x survivor_percent/100`` (a real single-life-vs-survivor modeling lever). Without
        a survivor election or a surviving spouse the pension terminates, as it does today.

        This runs before the estate transfer, so terminated pensions are removed from the registry
        (the generic reassignment won't touch them) and the survivor's pension is already re-owned
        by the spouse (the Benefit sweep in ``_remove_from_simulation`` won't delete it).
        """
        pensions = self.model.registries.pensions
        for pension in list(self.pensions):
            if spouse is not None and getattr(pension, "survivor_percent", 0) > 0:
                pension.benefit_amount *= pension.survivor_percent / 100.0
                # The continued stream is single-life on the survivor (no further survivor split).
                pension.survivor_percent = 0.0
                # The survivor annuity is in pay immediately: eligibility must not re-evaluate
                # against the survivor's own retirement status (a working 50-year-old widow still
                # receives the joint-and-survivor benefit from the year of death).
                pension.start_age = spouse.age
                pensions.unregister(self, pension)
                pensions.register(spouse, pension)
                pension.person = spouse
                self.model.event_log.add(
                    Event(
                        f"{spouse.name} continues {pension.company} pension at "
                        f"${pension.benefit_amount:,.0f}/yr after {self.name}'s death"
                    )
                )
            else:
                pensions.unregister(self, pension)
                pension.remove()

    def _owned_financial_agents(self) -> List["LifeModelAgent"]:
        """All balance-holding accounts (bank, brokerage, IRAs, HSA, 401k) owned by this person."""
        from ..base_classes import FinancialAccount

        return [a for a in self.model.agents if isinstance(a, FinancialAccount) and getattr(a, "person", None) is self]

    def _transfer_estate(self, inheritor: "Person", is_spouse: bool):
        """Move the estate to ``inheritor``.

        Accounts with a designated (surviving) ``beneficiary`` are routed to that beneficiary
        first — designation beats the will, as with real retirement accounts. The residual estate
        then goes to ``inheritor``: a surviving spouse inherits via the unlimited marital deduction
        (no estate tax) and rolls pre-tax accounts over tax-free; a non-spouse inheritor receives
        pre-tax accounts per ``estate.inherited_pretax_mode``, and the estate above the exemption
        is subject to estate tax.

        Estate tax: the unlimited marital deduction shelters only the portion actually passing to
        the surviving spouse (the residual when the spouse is the residual inheritor, plus any
        spousal-designated accounts and the spouse's share of revocable-trust payouts). Everything
        passing to non-spouse recipients — designated or residual — is in the taxable base.
        Documented simplification: the tax is *charged* to the residual inheritor (no
        per-beneficiary apportionment of who pays), even when a designation created the liability.
        """
        gross_estate = self._gross_estate_value()
        taxable_base = max(0.0, gross_estate - self._marital_share(is_spouse))

        self._transfer_designated_accounts()

        if not is_spouse:
            self._liquidate_pretax_to(inheritor)

        self._reassign_owned_agents(inheritor)

        self._apply_estate_tax(inheritor, taxable_base)

        self.model.event_log.add(Event(f"{self.name}'s estate transferred to {inheritor.name}"))

    def _marital_share(self, is_spouse: bool) -> float:
        """Value of the estate passing to the surviving spouse (sheltered by the unlimited
        marital deduction).

        Counts spousal-designated account balances, the spouse's share of revocable-trust payouts,
        and — when the spouse is the residual inheritor — the residual estate (everything not
        designated away and not passing through a trust to other beneficiaries). A revocable trust
        with no surviving beneficiaries escheats to the residual estate and is counted there.
        """
        from ..estate.trust import TrustType

        spouse = self.spouse if (self.spouse is not None and not self.spouse.is_deceased) else None
        if spouse is None:
            return 0.0

        share = 0.0
        passing_outside_residual = 0.0
        for acct in self._owned_financial_agents():
            beneficiary = getattr(acct, "beneficiary", None)
            if beneficiary is None or beneficiary.is_deceased or beneficiary is self:
                continue
            balance = getattr(acct, "balance", 0.0)
            passing_outside_residual += balance
            if beneficiary is spouse:
                share += balance
        for trust in self.trusts:
            if trust.trust_type != TrustType.REVOCABLE:
                continue
            survivors = [b for b in trust.beneficiaries if not b.is_deceased]
            if survivors:
                passing_outside_residual += trust.balance
                if spouse in survivors:
                    share += trust.balance / len(survivors)
            # else: the corpus escheats to the residual estate (counted in the residual below).
        if is_spouse:
            residual = self._gross_estate_value() - passing_outside_residual
            share += max(0.0, residual)
        return share

    def _transfer_designated_accounts(self):
        """Route each account with a designated surviving beneficiary directly to that person.

        A designated pre-tax balance passing to someone other than the surviving spouse is
        distributed under ``estate.inherited_pretax_mode`` (10-year spread or lump sum), exactly
        like the residual path; a spouse designee gets the tax-free rollover. A predeceased
        beneficiary is skipped, so the account falls through to the residual-estate path.
        """
        from ..account.job401k import Job401kAccount
        from ..account.traditional_IRA import TraditionalIRA

        spouse = self.spouse if (self.spouse is not None and not self.spouse.is_deceased) else None
        for acct in self._owned_financial_agents():
            beneficiary = getattr(acct, "beneficiary", None)
            if beneficiary is None or beneficiary.is_deceased or beneficiary is self:
                continue
            if beneficiary is not spouse:
                # Non-spouse designee: the pre-tax portion is a taxable inheritance.
                pretax = 0.0
                if isinstance(acct, Job401kAccount):
                    pretax = acct.pretax_balance
                    acct.pretax_balance = 0.0
                elif isinstance(acct, TraditionalIRA):
                    pretax = acct.balance
                    acct.balance = 0.0
                if pretax > 0:
                    self._distribute_inherited_pretax(pretax, beneficiary)
            acct.person = beneficiary
            if hasattr(acct, "owner"):
                acct.owner = beneficiary
            # Registry-backed accounts (bank accounts) also move their registry entry so the
            # designee's account properties see them and the residual transfer doesn't re-route them.
            for reg in self.model.registries.iter_registries():
                if reg.unregister(self, acct):
                    reg.register(beneficiary, acct)
            self.model.event_log.add(Event(f"{self.name}'s designated account transferred to {beneficiary.name}"))

    def _gross_estate_value(self) -> float:
        """Approximate transferable estate value (account balances plus home equity).

        Revocable-trust balances are included (the grantor keeps control, so they remain in the
        gross estate); irrevocable-trust balances are excluded — that exclusion is the modelable
        estate-planning lever (see :class:`~life_model.estate.trust.Trust`).
        """
        from ..estate.trust import TrustType

        total = sum(getattr(a, "balance", 0.0) for a in self._owned_financial_agents())
        for home in self.homes:
            equity = home.home_value - (home.mortgage.principal if home.mortgage is not None else 0.0)
            total += max(0.0, equity)
        total += sum(t.balance for t in self.trusts if t.trust_type == TrustType.REVOCABLE)
        return total

    def _liquidate_pretax_to(self, inheritor: "Person"):
        """Pass the decedent's pre-tax balances to a non-spouse beneficiary.

        Under ``estate.inherited_pretax_mode == "ten_year"`` (default) the balance moves into an
        :class:`~life_model.account.inherited.InheritedPretaxAccount` that spreads the distribution
        (and its tax) over ten years per the SECURE Act. Under ``"lump_sum"`` the whole balance is
        distributed and taxed to the beneficiary in the death year (the Plan 09 simplification,
        retained for comparability).
        """
        from ..account.job401k import Job401kAccount
        from ..account.traditional_IRA import TraditionalIRA

        total_pretax = 0.0
        for acct in self._owned_financial_agents():
            if isinstance(acct, Job401kAccount):
                total_pretax += acct.pretax_balance
                acct.pretax_balance = 0.0
            elif isinstance(acct, TraditionalIRA):
                total_pretax += acct.balance
                acct.balance = 0.0
        self._distribute_inherited_pretax(total_pretax, inheritor)

    def _distribute_inherited_pretax(self, amount: float, beneficiary: "Person"):
        """Pass ``amount`` of inherited pre-tax money to a non-spouse ``beneficiary`` per the
        configured ``estate.inherited_pretax_mode`` (see ``_liquidate_pretax_to``)."""
        if amount <= 0:
            return
        mode = self.model.config.estate.inherited_pretax_mode
        if mode == "lump_sum":
            beneficiary.income.add(IncomeType.PRETAX_DISTRIBUTION, amount)
            beneficiary.receive_cash(amount, source=f"inherited retirement from {self.name}")
        else:  # "ten_year"
            from ..account.inherited import InheritedPretaxAccount

            InheritedPretaxAccount(beneficiary, balance=amount, decedent_name=self.name)

    def _reassign_owned_agents(self, inheritor: "Person"):
        """Reassign ownership of every owned agent (accounts, homes, jobs, insurance, debts) to
        ``inheritor`` so they keep participating in the simulation under the new owner."""
        # Non-registry financial accounts (brokerage, IRAs, HSA, 401k) reference ``person`` directly.
        for acct in self._owned_financial_agents():
            acct.person = inheritor
        # Registry-backed items: move the registry entry and update the owner reference.
        for reg in self.model.registries.iter_registries():
            for item in list(reg.get_items(self)):
                if hasattr(item, "person"):
                    item.person = inheritor
                if hasattr(item, "owner"):
                    item.owner = inheritor
        self.model.registries.transfer_owner(self, inheritor)

    def _settle_trusts_on_death(self, inheritor: Optional["Person"]):
        """Settle this person's trusts at death: revocable trusts pay out to their beneficiaries
        (outside ``_find_beneficiary``), escheating to the residual ``inheritor`` when no trust
        beneficiary survives; irrevocable trusts survive untouched."""
        from ..estate.trust import TrustType

        for trust in list(self.trusts):
            if trust.trust_type == TrustType.REVOCABLE:
                trust.pay_out_at_grantor_death(residual_inheritor=inheritor)

    def _apply_estate_tax(self, inheritor: "Person", taxable_base: float):
        """Apply estate tax on ``taxable_base`` (the gross estate net of the marital share).

        The tax is charged to the residual inheritor (documented simplification: no
        per-beneficiary apportionment of who pays).
        """
        federal = self.model.config.tax.federal
        exemption = getattr(federal, "estate_tax_exemption", 15000000)
        # Lifetime taxable gifts (e.g. irrevocable trust funding above the annual exclusion)
        # consume the unified exemption.
        exemption = max(0.0, exemption - self.estate_exemption_used)
        rate = getattr(federal, "estate_tax_rate", 40.0)
        taxable = max(0.0, taxable_base - exemption)
        estate_tax = taxable * (rate / 100)
        if estate_tax > 0:
            inheritor.pay_bills(estate_tax)
            self.model.event_log.add(Event(f"Estate tax of ${estate_tax:,.0f} paid on {self.name}'s estate"))

    def _apply_survivor_adjustments(self, spouse: "Person"):
        """Update the surviving spouse: unlink marriage, schedule the filing-status change, and
        approximate the Social Security survivor benefit."""
        spouse.spouse = None
        spouse._widowed_year = self.model.year
        # Social Security survivor approximation: the survivor receives at least the deceased's
        # benefit (max of own vs. deceased's), applied as a monthly floor once benefits start.
        if self.social_security is not None and spouse.social_security is not None:
            deceased_monthly = self.social_security.get_pia()
            spouse.social_security.survivor_pia_floor = max(
                getattr(spouse.social_security, "survivor_pia_floor", 0.0), deceased_monthly
            )

    def _remove_from_simulation(self):
        """Remove the deceased and any now-empty owned agents from the model, and zero the
        deceased's statistics so aggregate reporting no longer counts them."""
        # Any financial accounts still owned by the deceased were emptied (non-spouse pre-tax) or
        # never transferred; remove them so they stop stepping.
        for acct in self._owned_financial_agents():
            acct.remove()
        # Pensions and other benefits are life-only in v1: they stop at death.
        from ..base_classes import Benefit

        for benefit in [a for a in self.model.agents if isinstance(a, Benefit) and getattr(a, "person", None) is self]:
            benefit.remove()
        # Drop the deceased from their family so no tax unit is built for them.
        if self in self.family.members:
            self.family.members.remove(self)
        # Zero the deceased's own statistics so the model's per-agent sums exclude them.
        for stat in (*LifeModel.STATS, *LifeModel.EXTRA_STATS):
            setattr(self, stat.name, 0)
        self.remove()

    def post_step(self):
        self.income.clear()


class Spending(LifeModelAgent):
    def __init__(self, model: LifeModel, base: float = 0, yearly_increase: Optional[float] = 0):
        """Spending

        Args:
            model (LifeModel): LifeModel instance.
            base (float): Base spending amount.
            yearly_increase (float, optional): Yearly percentage increase in spending. 10 = 10%.
                Pass None to grow with the economy's inflation each year. Defaults to 0 (no increase).
        """
        super().__init__(model)
        self.base = base
        self._yearly_increase_override = yearly_increase
        self.one_time_expenses = 0

    @property
    def yearly_increase(self) -> float:
        """Yearly percentage increase: the explicit override if set, else the economy's inflation."""
        if self._yearly_increase_override is not None:
            return self._yearly_increase_override
        return self.model.economy.inflation(self.model.year)

    @yearly_increase.setter
    def yearly_increase(self, value: Optional[float]) -> None:
        self._yearly_increase_override = value

    def add_expense(self, amount: float):
        """Adds a one-time expense.

        Args:
            amount (float): Amount of expense to add.
        """
        self.one_time_expenses += amount

    def get_yearly_spending(self) -> float:
        """Gets yearly spending."""
        return self.base + self.one_time_expenses

    def adjust_base(self, base_percent: float):
        """Adjusts base spending.

        Args:
            base_percent (float): Percentage increase in spending. 50 = 50%.
        """
        self.base = self.base * (base_percent / 100)

    def post_step(self):
        # Consume-then-advance: the year's spending is read during the step stage; only after
        # it has been spent do we clear one-time expenses and apply the yearly increase.
        self.base += self.base * (self.yearly_increase / 100)
        self.one_time_expenses = 0
