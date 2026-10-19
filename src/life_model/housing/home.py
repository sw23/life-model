# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import ClassVar

from ..base_classes import LOAN_RENAMES, Loan
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..model import Event, EventKind, LifeModel, LifeModelAgent
from ..people.person import Person
from ..tax.federal import FilingStatus
from ..tax.income import IncomeType


class Home(LifeModelAgent):
    """A home: paid for monthly (a twelfth of the year's property tax, insurance, upkeep, HOA and PMI,
    plus one mortgage payment) with the household's bills, appreciated once a year at year end
    (property tax is assessed on the value through the year)."""

    STATS_OWNED = frozenset({"stat_home_value", "stat_home_equity"})
    # Appreciation at year end, after the year's taxes (0) read the year's property tax.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 10}

    @deprecated_arguments({"person": "owner", "value_yearly_increase": "value_growth_pct"})
    def __init__(
        self,
        owner: Person,
        name: str,
        purchase_price: float,
        value_growth_pct: float | None,
        down_payment: float,
        mortgage: "Mortgage",
        expenses: "HomeExpenses",
        purchase: bool = False,
        *,
        current_value: float | None = None,
        cost_basis: float | None = None,
        purchase_year: int | None = None,
        pmi: bool = True,
        pmi_monthly: float | None = None,
        closing_cost_percent: float | None = None,
    ):
        """Home

        Args:
            owner (Person): Primary resident or person that pays the bills (``person=`` is deprecated).
            name (string): Name of the house or neighborhood.
            purchase_price (float): Purchase price of the home (its "original value" for PMI).
            value_growth_pct (float): Percentage of yearly home value appreciation. Pass None to
                appreciate with the economy's home-appreciation rate each year (``value_yearly_increase=``
                is deprecated).
            down_payment (float): Amount of down payment.
            mortgage (Mortgage): Mortgage associated with the home.
            expenses (HomeExpenses): Home expenses associated with the home.
            purchase (bool, optional): When True, the home is being bought now: the down payment
                and closing costs are withdrawn from the owner's accounts. Defaults to False (the
                home is already owned at the start of the simulation, so no cash changes hands).
            current_value (float, optional): Market value today, for a home bought before the run
                (keyword-only). Defaults to ``purchase_price``.
            cost_basis (float, optional): The §121 cost basis (price plus improvements so far).
                Defaults to ``purchase_price``.
            purchase_year (int, optional): Year bought, for the §121 two-year ownership test. Unknown
                (None) for a home owned before the run passes the test; a home bought in the run uses
                its purchase month.
            pmi (bool, optional): False: the mortgage carries no private mortgage insurance (e.g. it
                was cancelled already, or a lender-paid or piggyback loan). Defaults to True.
            pmi_monthly (float, optional): The statement's monthly PMI premium instead of the
                configured rate times the balance.
            closing_cost_percent (float, optional): Closing costs on a purchase, percent of the price
                (configured default when None).
        """
        person = owner
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.purchase_price = purchase_price
        self._value_yearly_increase_override = value_growth_pct
        self.down_payment = down_payment
        self.mortgage = mortgage
        self.expenses = expenses
        self.expenses.home = self
        self.home_value: float = self.purchase_price if current_value is None else float(current_value)
        #: The value PMI's loan-to-value is measured against (Homeowners Protection Act "original
        #: value": the price, or the appraisal for a refinance).
        self.original_value: float = float(purchase_price)

        # Cost basis for the §121 capital-gains calculation on sale: purchase price plus the
        # cumulative cost of improvements made while owned.
        self.cost_basis: float = self.purchase_price if cost_basis is None else float(cost_basis)
        self.total_improvements: float = 0.0
        self.sold: bool = False
        self.pmi = pmi
        self.pmi_monthly = pmi_monthly
        self.closing_cost_percent = closing_cost_percent
        #: ``(year, month)`` the home was bought (None: owned before the run, date unknown).
        self.purchase_period: tuple[int, int] | None = None if purchase_year is None else (int(purchase_year), 1)
        if purchase:
            self.purchase_period = (self.model.year, self.model.month)
        self.expenses._init_assessment()

        #: The last housing payment by line (see :meth:`make_monthly_payment` and
        #: :meth:`make_yearly_payment`).
        self.year_payment: dict[str, float] = {}

        # Bind the mortgage to this owner (a Mortgage is constructed before its Home, so it defers
        # agent registration until the Home adopts it).
        if self.mortgage is not None:
            self.mortgage.home = self
            self.mortgage._attach(person)

        # Register with the model registry
        self.model.registries.homes.register(person, self)

        if purchase:
            self.buy()
        else:
            # A home that simply appears mid-run (not bought) brings its value and its mortgage.
            self.model.ledger.post_opening(self, self.home_value)
            if self.mortgage is not None:
                self.model.ledger.post_opening(self.mortgage, self.mortgage.principal, liability=True)

    @property
    def value_yearly_increase(self) -> float:
        """Yearly appreciation percent: the explicit override if set, else the economy's rate."""
        if self._value_yearly_increase_override is not None:
            return self._value_yearly_increase_override
        return self.model.economy.home_appreciation(self.model.year)

    @value_yearly_increase.setter
    def value_yearly_increase(self, value: float | None) -> None:
        self._value_yearly_increase_override = value

    @property
    def yearly_expenses_due(self) -> float:
        mortgage_due = self.mortgage.get_payment_due_for_year() if self.mortgage is not None else 0.0
        return self.expenses.get_yearly_spending() + mortgage_due

    @property
    def property_tax_for_year(self) -> float:
        """Property tax for the year (deductible as SALT): see :meth:`HomeExpenses.property_tax_for_year`."""
        return self.expenses.property_tax_for_year()

    @property
    def loan_to_value(self) -> float:
        """Loan-to-value ratio as a percentage of the original value (the purchase price)."""
        if self.mortgage is None or self.original_value <= 0:
            return 0.0
        return self.mortgage.principal / self.original_value * 100

    def pmi_active(self) -> bool:
        """Whether PMI is still charged (Homeowners Protection Act, 12 U.S.C. 4901-4902): it ends once
        the balance reaches the cancellation LTV (80% of the original value, by actual payments: the
        borrower is assumed to request cancellation), once the original schedule reaches the
        automatic-termination LTV (78%), or at the midpoint of the term (final termination)."""
        mortgage = self.mortgage
        if not self.pmi or mortgage is None or mortgage.principal <= 0 or self.original_value <= 0:
            return False
        housing = self.model.config.housing
        if self.loan_to_value <= housing.pmi_ltv_threshold:
            return False
        if mortgage.term_months and mortgage.payments_made >= mortgage.term_months / 2:
            return False
        from ..debt.terms import scheduled_balance

        scheduled = scheduled_balance(
            mortgage.loan_amount, mortgage.yearly_interest_rate, mortgage.monthly_payment, mortgage.payments_made
        )
        return scheduled / self.original_value * 100 > housing.pmi_termination_ltv

    def _pmi_for_year(self) -> float:
        """Private mortgage insurance charged this year (a year's premium; a twelfth is paid monthly)."""
        if not self.pmi_active():
            return 0.0
        if self.pmi_monthly is not None:
            return self.pmi_monthly * 12
        return self.mortgage.principal * (self.model.config.housing.pmi_rate / 100)

    def section_121_exclusion(self) -> float:
        """The §121 exclusion available on a sale now: the filing status's maximum, or 0 when the home
        was bought less than two years ago (the ownership test, IRC §121(a); the use test is assumed
        met, and the reduced exclusion of §121(c) is not modeled). A home owned before the run with no
        purchase year passes."""
        housing = self.model.config.housing
        if self.person.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            exclusion = housing.section_121_exclusion.married_filing_jointly
        else:
            exclusion = housing.section_121_exclusion.single
        if self.purchase_period is not None:
            from ..debt.terms import months_between

            if months_between(self.purchase_period, (self.model.year, self.model.month)) < 24:
                return 0.0
        return exclusion

    def buy(self):
        """Withdraw the down payment and closing costs from the owner's household.

        Used when a home is purchased during the simulation (``purchase=True``). The cash comes
        through the household waterfall (:meth:`TaxUnit.pay_bills`): both spouses' banks, then
        brokerage, Roth basis, pre-tax accounts and the remaining Roth money; the gains, ordinary
        income and penalties it creates are taxed when the year settles. Any amount the household
        can't cover becomes debt on the owner.
        """
        from ..people.tax_unit import TaxUnit

        closing_pct = self.closing_cost_percent
        if closing_pct is None:
            closing_pct = self.model.config.housing.closing_cost_percent
        closing_costs = self.purchase_price * (closing_pct / 100)
        cash_needed = self.down_payment + closing_costs
        ledger = self.model.ledger
        cause = f"purchase of {self.name}"
        unit = TaxUnit.for_member(self.person)
        # The down payment buys equity (a transfer into the home); the mortgage lends the rest of
        # the price (borrowed into the home); closing costs are spent.
        with ledger.caused_by(cause):
            unpaid = unit.pay_bills(self.down_payment, kind=FlowKind.HOUSING, to_account=self, cause=cause)
            self.person.add_debt(unpaid, to_account=self, cause=cause)
            unpaid = unit.pay_bills(closing_costs, kind=FlowKind.HOUSING, sink="closing costs", cause=cause)
            self.person.add_debt(unpaid, kind=FlowKind.HOUSING, sink="closing costs", cause=cause)
        principal = self.mortgage.principal if self.mortgage is not None else 0.0
        if self.mortgage is not None:
            ledger.post(
                principal, FlowKind.BORROW, from_account=self.mortgage, to_account=self, cause=cause, agent=self.person
            )
        # A price not covered by the down payment plus the mortgage is value from outside the model.
        gap = self.home_value - self.down_payment - principal
        if abs(gap) > 0.005:
            ledger.post(
                gap,
                FlowKind.OPENING_BALANCE,
                to_account=self,
                source="price not covered by down payment and mortgage",
                cause=cause,
                agent=self.person,
            )
        self.model.event_log.add(
            Event(
                EventKind.HOME_BOUGHT,
                person=self.person,
                amount=self.purchase_price,
                account=self,
                cause=cause,
                message=f"{self.person.name} bought {self.name} for ${self.purchase_price:,.0f} (down + closing "
                f"${cash_needed:,.0f})",
            )
        )

    def sell(self, selling_cost_percent: float | None = None) -> float:
        """Sell the home: pay off the mortgage, realize equity to cash, and tax the gain.

        The taxable gain above the §121 primary-residence exclusion (2-of-5-year residency assumed)
        is added to the owner's income. Net proceeds (sale price − selling costs − mortgage payoff)
        are credited to the owner's bank account. Returns the net proceeds.
        """
        if self.sold:
            return 0.0
        housing = self.model.config.housing
        if selling_cost_percent is None:
            selling_cost_percent = housing.selling_cost_percent

        sale_price = self.home_value
        selling_costs = sale_price * (selling_cost_percent / 100)
        mortgage_payoff = self.mortgage.principal if self.mortgage is not None else 0.0
        helocs = [line for line in self.person.home_equity_lines if line.home is self]
        heloc_payoff = sum(line.balance for line in helocs)

        cost_basis = self.cost_basis + self.total_improvements
        gain = sale_price - selling_costs - cost_basis
        exclusion = self.section_121_exclusion()
        taxable_gain = max(0.0, gain - exclusion)
        if taxable_gain > 0:
            # A residence held long enough to qualify for §121 is by definition held over a year,
            # so the excess above the exclusion is always a long-term gain.
            self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, taxable_gain, source="home_sale")

        net_proceeds = sale_price - selling_costs - mortgage_payoff - heloc_payoff
        ledger = self.model.ledger
        cause = f"sale of {self.name}"
        for line in helocs:
            line.pay_off_from_sale(cause)
        # The home's value leaves the balance sheet: selling costs are spent, the mortgage is paid
        # off from the price, and the rest arrives as cash.
        ledger.post(
            selling_costs, FlowKind.HOUSING, from_account=self, sink="selling costs", cause=cause, agent=self.person
        )
        if self.mortgage is not None:
            ledger.post(
                mortgage_payoff,
                FlowKind.HOUSING,
                from_account=self,
                to_account=self.mortgage,
                cause=f"{cause}: mortgage payoff",
                agent=self.person,
            )
            self.mortgage.principal = 0.0
            self.model.registries.mortgages.unregister(self.person, self.mortgage)
        if net_proceeds > 0:
            self.person.receive_cash(net_proceeds, source=cause, kind=FlowKind.SALE, from_account=self, cause=cause)
        elif net_proceeds < 0:
            # Underwater: the sale price doesn't cover the payoff and selling costs. The owner brings
            # the difference to closing (through the household waterfall; whatever can't be raised
            # becomes debt) instead of the lender writing it off.
            from ..people.tax_unit import TaxUnit

            shortfall = -net_proceeds
            unpaid = TaxUnit.for_member(self.person).pay_bills(
                shortfall, kind=FlowKind.HOUSING, to_account=self, cause=f"{cause}: underwater payoff"
            )
            self.person.add_debt(unpaid, to_account=self, cause=f"{cause}: underwater payoff")

        self.sold = True
        self.model.registries.homes.unregister(self.person, self)
        self.model.event_log.add(
            Event(
                EventKind.HOME_SOLD,
                person=self.person,
                amount=sale_price,
                account=self,
                cause=cause,
                message=f"{self.person.name} sold {self.name} for ${sale_price:,.0f} "
                f"(net ${net_proceeds:,.0f}, taxable gain ${taxable_gain:,.0f})",
                net_proceeds=net_proceeds,
                taxable_gain=taxable_gain,
            )
        )
        return net_proceeds

    def make_monthly_payment(self) -> float:
        """Pay this month's housing costs: a twelfth of the year's home expenses and PMI, and one
        mortgage payment. Improvement spending accrues to the cost basis. ``year_payment`` holds the
        month's lines. Returns the cash paid."""
        if self.sold:
            self.year_payment = {}
            return 0.0
        lines = {name: amount / 12 for name, amount in self.expenses.year_lines().items()}
        self.total_improvements += self.expenses.improvement_amount / 12
        pmi = self._pmi_for_year() / 12
        if pmi:
            lines["pmi"] = pmi
        total = sum(lines.values())
        if self.mortgage is not None:
            before = self.mortgage.principal
            interest_before = self.mortgage.interest_paid_this_year
            paid = self.mortgage.service_month()
            if before > 0:
                lines["mortgage"] = paid
                lines["mortgage_interest"] = self.mortgage.interest_paid_this_year - interest_before
                lines["mortgage_principal_before"] = before
            total += paid
        self.year_payment = lines
        return total

    def make_yearly_payment(self, extra_to_principal: float = 0) -> float:
        """Pay a year of housing costs at once: home expenses, PMI, and the mortgage (twelve
        payments). For direct callers; the engine pays housing monthly (:meth:`make_monthly_payment`).
        Improvement spending accrues to the cost basis. Returns the total cash paid.
        """
        if self.sold:
            return 0.0
        expenses_paid = self.expenses.get_yearly_spending()
        # Improvements add to the home's cost basis.
        self.total_improvements += self.expenses.improvement_amount
        pmi_paid = self._pmi_for_year()
        mortgage_paid = 0.0
        self.year_payment = self.expenses.year_lines()
        if pmi_paid:
            self.year_payment["pmi"] = pmi_paid
        if self.mortgage is not None:
            principal_before = self.mortgage.principal
            mortgage_paid = self.mortgage.make_yearly_payment(self.mortgage.monthly_payment, extra_to_principal)
            self.year_payment["mortgage"] = mortgage_paid
            self.year_payment["mortgage_interest"] = self.mortgage.interest_paid_this_year
            self.year_payment["mortgage_principal_before"] = principal_before
        return expenses_paid + pmi_paid + mortgage_paid

    def _repr_html_(self):
        monthly = self.mortgage.monthly_payment if self.mortgage is not None else 0.0
        return f"{html.escape(self.name)}, purchase price ${self.purchase_price:,}, " + f"monthly mortgage ${monthly:,}"

    def collect_stats(self):
        """Year-end value and equity (0 once sold, or when left behind by a decedent with no heir)."""
        if self.sold or self.person.is_deceased:
            self.stat_home_value = self.stat_home_equity = 0.0
            return
        self.stat_home_value = self.home_value
        principal = self.mortgage.principal if self.mortgage is not None else 0.0
        self.stat_home_equity = self.home_value - principal

    def on_year_end(self):
        # Appreciate at year end (consume-then-advance): property tax for the year is assessed
        # on the value through the year.
        if self.sold or self.person.is_deceased:
            # A home left behind by a decedent with no heir is off every balance sheet.
            return
        appreciation = self.home_value * (self.value_yearly_increase / 100)
        self.home_value += appreciation
        self.model.ledger.post(
            appreciation, FlowKind.GROWTH, to_account=self, source="housing market", agent=self.person
        )


class HomeExpenses(LifeModelAgent):
    """The recurring costs of owning a home: property tax, homeowner's insurance, maintenance,
    improvements and HOA dues (a year's amounts; a twelfth is paid each month).

    Property tax is, in order of preference: a dollar amount (``property_tax_annual``, grown by
    ``property_tax_growth_pct``); a percent of an assessed value (``assessed_value``, grown by the
    home's appreciation, capped at ``assessment_growth_cap_pct`` — e.g. California's 2%); or a percent
    of the market value. Insurance is a dollar premium (``insurance_annual``) or a percent of the market
    value. A growth rate of None follows the economy's inflation (``inflation=True`` makes that the
    default for maintenance, improvements and HOA dues).
    """

    # Escalators at year end, after the year's taxes (0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 10}

    @deprecated_arguments(
        {
            "property_tax_percent": "property_tax_pct",
            "home_insurance_percent": "insurance_pct",
            "maintenance_amount": "maintenance_annual",
            "maintenance_increase": "maintenance_growth_pct",
            "improvement_amount": "improvement_annual",
            "improvement_increase": "improvement_growth_pct",
            "hoa_amount": "hoa_annual",
            "hoa_increase": "hoa_growth_pct",
        }
    )
    def __init__(
        self,
        model: LifeModel,
        property_tax_pct: float = 0.0,
        insurance_pct: float = 0.0,
        maintenance_annual: float = 0.0,
        maintenance_growth_pct: float | None = 0.0,
        improvement_annual: float = 0.0,
        improvement_growth_pct: float | None = 0.0,
        hoa_annual: float = 0.0,
        hoa_growth_pct: float | None = 0.0,
        *,
        property_tax_annual: float | None = None,
        property_tax_growth_pct: float | None = None,
        assessed_value: float | None = None,
        assessment_growth_cap_pct: float | None = None,
        insurance_annual: float | None = None,
        insurance_growth_pct: float | None = None,
        inflation: bool = False,
    ):
        """Home Expenses

        Args:
            property_tax_pct (float): Property tax percentage paid yearly, of the assessed value when
                given, else of the home value.
            insurance_pct (float): Yearly home insurance cost as percentage of home value.
            maintenance_annual (float): Yearly cost of home maintenance.
            maintenance_growth_pct (float): Yearly percentage increase of maintenance costs (None: inflation).
            improvement_annual (float): Yearly cost of improvements.
            improvement_growth_pct (float): Yearly percentage increase of improvement costs (None: inflation).
            hoa_annual (float): Yearly HOA dues.
            hoa_growth_pct (float): Yearly percentage increase of HOA dues (None: inflation).
            property_tax_annual (float, optional): The tax bill in dollars per year (keyword-only;
                replaces ``property_tax_pct``).
            property_tax_growth_pct (float, optional): Yearly growth of ``property_tax_annual`` (None:
                inflation).
            assessed_value (float, optional): The assessor's value the percent applies to.
            assessment_growth_cap_pct (float, optional): Cap on the assessed value's yearly growth (it
                otherwise follows the home's appreciation).
            insurance_annual (float, optional): The homeowner's insurance premium in dollars per year
                (replaces ``insurance_pct``).
            insurance_growth_pct (float, optional): Yearly growth of ``insurance_annual`` (None: inflation).
            inflation (bool, optional): True: maintenance, improvements and HOA dues grow with the
                economy's inflation (their growth arguments are ignored).

        The names (``property_tax_percent``, ``home_insurance_percent``, ``maintenance_amount``,
        ``maintenance_increase``, ``improvement_amount``, ``improvement_increase``, ``hoa_amount``,
        ``hoa_increase``) are deprecated aliases.
        """
        super().__init__(model)
        self.property_tax_percent = property_tax_pct
        self.home_insurance_percent = insurance_pct
        self.maintenance_amount = maintenance_annual
        self.improvement_amount = improvement_annual
        self.hoa_amount = hoa_annual
        if inflation:
            maintenance_growth_pct = improvement_growth_pct = hoa_growth_pct = None
        self._maintenance_increase = maintenance_growth_pct
        self._improvement_increase = improvement_growth_pct
        self._hoa_increase = hoa_growth_pct
        self.inflation = inflation
        self.property_tax_annual = property_tax_annual
        self.property_tax_growth_pct = property_tax_growth_pct
        self.assessed_value = assessed_value
        self.assessment_growth_cap_pct = assessment_growth_cap_pct
        self.insurance_annual = insurance_annual
        self.insurance_growth_pct = insurance_growth_pct
        self.home: Home | None = None

    def _init_assessment(self) -> None:
        """Called by the home once attached (nothing to do yet: the assessed value is given)."""

    def _growth(self, override: float | None) -> float:
        return self.model.economy.inflation(self.model.year) if override is None else override

    @property
    def maintenance_increase(self) -> float:
        return self._growth(self._maintenance_increase)

    @maintenance_increase.setter
    def maintenance_increase(self, value: float | None) -> None:
        self._maintenance_increase = value

    @property
    def improvement_increase(self) -> float:
        return self._growth(self._improvement_increase)

    @improvement_increase.setter
    def improvement_increase(self, value: float | None) -> None:
        self._improvement_increase = value

    @property
    def hoa_increase(self) -> float:
        return self._growth(self._hoa_increase)

    @hoa_increase.setter
    def hoa_increase(self, value: float | None) -> None:
        self._hoa_increase = value

    def property_tax_for_year(self) -> float:
        """This year's property tax: the dollar bill, a percent of the assessed value, or a percent of
        the home's market value."""
        if self.property_tax_annual is not None:
            return self.property_tax_annual
        base = self.assessed_value
        if base is None:
            base = self.home.home_value if self.home is not None else 0.0
        return base * (self.property_tax_percent / 100)

    def insurance_for_year(self) -> float:
        """This year's homeowner's insurance: the dollar premium, or a percent of the market value."""
        if self.insurance_annual is not None:
            return self.insurance_annual
        if self.home is None:
            return 0.0
        return self.home.home_value * (self.home_insurance_percent / 100)

    def get_yearly_spending(self):
        return sum(self.year_lines().values())

    def year_lines(self) -> dict[str, float]:
        """:meth:`get_yearly_spending` by line (property tax, insurance, maintenance, improvements, HOA)."""
        lines = {}
        if self.home is not None or self.property_tax_annual is not None:
            lines["property_tax"] = self.property_tax_for_year()
        if self.home is not None or self.insurance_annual is not None:
            lines["home_insurance"] = self.insurance_for_year()
        lines["maintenance"] = self.maintenance_amount
        lines["improvements"] = self.improvement_amount
        lines["hoa"] = self.hoa_amount
        return {name: amount for name, amount in lines.items() if amount}

    def on_year_end(self):
        # Escalators run after the year's expenses have been paid (consume-then-advance).
        self.maintenance_amount += self.maintenance_amount * (self.maintenance_increase / 100)
        self.improvement_amount += self.improvement_amount * (self.improvement_increase / 100)
        self.hoa_amount += self.hoa_amount * (self.hoa_increase / 100)
        if self.property_tax_annual is not None:
            self.property_tax_annual *= 1 + self._growth(self.property_tax_growth_pct) / 100
        if self.insurance_annual is not None:
            self.insurance_annual *= 1 + self._growth(self.insurance_growth_pct) / 100
        if self.assessed_value is not None and self.home is not None:
            growth = self.home.value_yearly_increase
            if self.assessment_growth_cap_pct is not None:
                growth = min(growth, self.assessment_growth_cap_pct)
            self.assessed_value *= 1 + growth / 100


# https://www.nerdwallet.com/mortgages/mortgage-calculator/calculate-mortgage-payment
# https://www.valuepenguin.com/mortgages/mortgage-payments-calculator
# https://www.investopedia.com/calculate-principal-and-interest-5211981
class Mortgage(Loan):
    STATS_OWNED = frozenset({"stat_mortgage_principal"})

    """A home mortgage.

    A Mortgage is an amortizing :class:`~life_model.base_classes.Loan`, so it shares the ABC's
    monthly amortization (with clamps and a zero-rate guard). Because a Mortgage is constructed
    *before* its :class:`Home` (which supplies the owning person/model), it initializes its loan data
    eagerly and defers agent registration until the Home adopts it via :meth:`_attach`.

    Entering a mortgage from its statement: ``origination`` (``"YYYY-MM"``) with the
    original amount and term gives the balance and payment today with no other input; or give the
    current balance (``principal``) and ``remaining_months``. ``monthly_payment`` is principal and
    interest; with ``escrow_monthly`` it is the statement's total payment and the escrow (property tax
    and insurance, which the home's expenses pay) is subtracted. Inputs that contradict each other
    raise :class:`~life_model.debt.terms.LoanTermsError` naming the field. A mortgage originated on or
    before 2017-12-15 is grandfathered under the $1,000,000 acquisition-debt limit (IRC
    §163(h)(3)(F)(i)(IV)).
    """

    @deprecated_arguments(
        {**{k: v for k, v in LOAN_RENAMES.items() if k != "person"}, "start_date": "start_year"},
        positional=("original_amount", "start_year", "term_years", "rate_pct", "current_balance", "payment_monthly"),
        keep_positional=0,
    )
    def __init__(
        self,
        *,
        original_amount: float | None = None,
        start_year: int | None = None,
        term_years: float | None = None,
        rate_pct: float | None = None,
        current_balance: float | None = None,
        payment_monthly: float | None = None,
        term_months: int | None = None,
        origination=None,
        payments_made: int | None = None,
        remaining_months: int | None = None,
        escrow_monthly: float | None = None,
        extra_principal_monthly: float = 0.0,
        schedule: str = "contract",
    ):
        """Mortgage

        Every argument is keyword-only (positional use and the names ``loan_amount``, ``start_date``,
        ``length_years``, ``yearly_interest_rate``, ``principal`` and ``monthly_payment`` are deprecated).

        Args:
            original_amount (float): Amount originally borrowed (may be omitted when the current balance
                and months remaining are given).
            start_year (int): Year the loan started. Without a ``current_balance``, a start year before
                the run is taken as an origination in January of that year (the balance is then the
                schedule's); prefer ``origination``.
            term_years (float): Original term in years (e.g. 30, 15); or ``term_months``.
            rate_pct (float): APR, percent.
            current_balance (float, optional): Current balance. Defaults to the schedule's (the original
                amount for a new loan).
            payment_monthly (float, optional): Principal and interest per month (computed when None);
                the statement's total when ``escrow_monthly`` is given.
            term_months (int, optional): Original term in months.
            origination (str, optional): Origination month ``"YYYY-MM"``.
            payments_made (int, optional): Payments made before the run (instead of ``origination``).
            remaining_months (int, optional): Months to maturity on the statement.
            escrow_monthly (float, optional): Escrow included in ``payment_monthly``.
            extra_principal_monthly (float, optional): Extra principal paid every month.
            schedule (str, optional): ``"contract"`` (default) or ``"statement"`` (trust a current balance
                above the original schedule; see :mod:`life_model.debt.terms`).
        """
        loan_amount, start_date, length_years = original_amount, start_year, term_years
        yearly_interest_rate, principal, monthly_payment = rate_pct, current_balance, payment_monthly
        # Intentionally does NOT call Loan.__init__ (no person/model yet); resolve the loan data
        # directly and register as an agent later in _attach.
        self.person = None
        self.start_date = start_date
        self.escrow_monthly = escrow_monthly
        if escrow_monthly is not None and monthly_payment is not None:
            if escrow_monthly > monthly_payment:
                raise ValueError("escrow_monthly is larger than the monthly payment it is part of")
            monthly_payment = monthly_payment - escrow_monthly
        self._term_inputs = {
            "loan_amount": loan_amount,
            "yearly_interest_rate": yearly_interest_rate,
            "length_years": length_years,
            "principal": principal,
            "monthly_payment": monthly_payment,
            "term_months": term_months,
            "origination": origination,
            "payments_made": payments_made,
            "remaining_months": remaining_months,
            "extra_principal_monthly": extra_principal_monthly,
            "schedule": schedule,
        }
        # Until the mortgage is attached (and knows the as-of month) an origination date is not applied.
        self._set_terms(as_of=None, **{**self._term_inputs, "origination": None})
        #: The most of the balance that is acquisition debt (None: all of it); a refinance's cash-out
        #: beyond the old balance is not, unless it paid for improvements (IRC §163(h)(3)(B)).
        self.acquisition_cap: float | None = None
        #: The most of the balance that is grandfathered acquisition debt (incurred on or before
        #: 2017-12-15: the $1M limit); a refinance keeps it up to the refinanced balance.
        self.grandfathered_cap = 0.0

        # Interest charged this year, accumulated payment by payment from each year start (the
        # itemized mortgage-interest deduction reads it). Until the first year starts it holds the
        # year's simple-interest estimate; a mortgage taken out mid-run starts at zero (_attach).
        self.interest_paid_this_year = self.get_interest_for_year()
        self._principal_paid_this_year = 0.0
        # Month-start balances this year (the average balance of IRS Pub. 936's limit worksheet).
        self._month_start_balances: list[float] = []

        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []
        self.stat_yearly_principal_payment_history = []
        self.stat_yearly_interest_payment_history = []

    def _origination_input(self, as_of: tuple[int, int]):
        """The origination to apply at attach: explicit, else a past ``start_date`` year without a balance."""
        explicit = self._term_inputs["origination"]
        if explicit is not None:
            return explicit
        start = self.start_date
        inputs = self._term_inputs
        if (
            start is not None
            and inputs["principal"] is None
            and inputs["payments_made"] is None
            and int(start) < as_of[0]
        ):
            return (int(start), 1)
        return None

    def _apply_origination(self, as_of: tuple[int, int]) -> None:
        """Resolve the terms against the as-of month once the model is known."""
        origination = self._origination_input(as_of)
        if origination is not None:
            self._set_terms(as_of=as_of, **{**self._term_inputs, "origination": origination})
            if self.model.current_stage is None and self.model.period == 0:
                self.interest_paid_this_year = self.get_interest_for_year()
        from ..debt.terms import parse_origination

        cutoff = parse_origination(self.model.config.tax.federal.mortgage_interest_grandfather_date)
        if self.origination is not None and cutoff is not None and self.origination <= cutoff:
            self.grandfathered_cap = self.principal

    # --- the year's qualified residence interest (IRS Pub. 936) ---

    def service_month(self) -> float:
        if self.principal > 0:
            self._month_start_balances.append(self.principal)
        return super().service_month()

    def on_year_start(self):
        super().on_year_start()
        self._month_start_balances = []

    @property
    def average_balance_this_year(self) -> float:
        """The year's average balance (of the month-start balances so far; the current balance before
        the first payment): Pub. 936's average-balance method for the debt limit."""
        balances = self._month_start_balances
        return sum(balances) / len(balances) if balances else self.principal

    def acquisition_split(self) -> tuple[float, float]:
        """``(acquisition, grandfathered)`` average balances this year: the part of the average balance
        that is acquisition debt, and the part of that incurred on or before 2017-12-15."""
        average = self.average_balance_this_year
        acquisition = average if self.acquisition_cap is None else min(average, self.acquisition_cap)
        return acquisition, min(acquisition, self.grandfathered_cap)

    def refinance(
        self,
        rate_pct: float,
        *,
        term_months: int | None = None,
        term_years: float | None = None,
        costs: float = 0.0,
        finance_costs: bool = False,
        cash_out: float = 0.0,
        cash_out_for_improvements: bool = False,
    ) -> float:
        """Refinance (see :meth:`Loan.refinance`). A cash-out beyond the old balance is home-equity
        debt (its interest not deductible after 2017) unless ``cash_out_for_improvements`` (it then
        adds to the home's cost basis as an improvement and is acquisition debt)."""
        self._cash_out_for_improvements = cash_out_for_improvements
        return super().refinance(
            rate_pct,
            term_months=term_months,
            term_years=term_years,
            costs=costs,
            finance_costs=finance_costs,
            cash_out=cash_out,
        )

    def _pay_cash_out(self, amount: float, cause: str) -> None:
        home = getattr(self, "home", None)
        if not getattr(self, "_cash_out_for_improvements", False) or home is None:
            super()._pay_cash_out(amount, cause)
            return
        # Spent on the home: an improvement (cost basis), borrowed from the mortgage.
        home.total_improvements += amount
        self.model.ledger.post(
            amount,
            FlowKind.BORROW,
            from_account=self,
            sink=f"improvements: {home.name}",
            cause=cause,
            agent=self.person,
        )

    def _on_refinance(self, old_principal: float, new_principal: float) -> None:
        # IRC §163(h)(3)(B)(i) and (F)(ii): refinanced acquisition debt stays acquisition (and keeps a
        # grandfathered date) up to the refinanced balance.
        acquisition_before = old_principal if self.acquisition_cap is None else min(old_principal, self.acquisition_cap)
        cash_out = new_principal - old_principal
        improvements = getattr(self, "_cash_out_for_improvements", False)
        self.grandfathered_cap = min(self.grandfathered_cap, acquisition_before)
        if improvements:
            self.acquisition_cap = None if self.acquisition_cap is None else self.acquisition_cap + cash_out
        else:
            self.acquisition_cap = acquisition_before

    def collect_stats(self):
        self.stat_mortgage_principal = 0.0 if self.person.is_deceased else self.principal

    def _attach(self, person: Person) -> None:
        """Bind this mortgage to its owner and register it as a model agent."""
        self.person = person
        LifeModelAgent.__init__(self, person.model)
        self._apply_origination((self.model.year, self.model.month))
        if self.model.current_stage is not None or self.model.period > 0:
            self.interest_paid_this_year = 0.0  # taken out mid-run: this year's payments accumulate
        self.model.registries.mortgages.register(person, self)

    def get_monthly_payment(self) -> float:
        """Fully-amortizing monthly payment (guards the 0% case via the Loan ABC)."""
        return self.calculate_monthly_payment()

    def get_interest_for_year(self) -> float:
        """A full year's simple interest on the current principal."""
        return self.get_interest_amount("year")

    def get_payment_due_for_year(self) -> float:
        """Approximate cash due this year (a year of scheduled payments, capped at payoff)."""
        yearly_payment = self.monthly_payment * 12
        return min(yearly_payment, self.principal + self.get_interest_amount("year"))


def qualified_residence_interest(person: Person) -> float:
    """The person's deductible home mortgage interest this year (IRC §163(h)(3), IRS Pub. 936).

    Interest on acquisition debt (mortgages, refinanced up to the old balance, and the part of a home
    equity line or cash-out used to improve the home) is deductible within the debt limit: $750,000
    ($375,000 married filing separately), reduced by any debt incurred on or before 2017-12-15, which
    has its own $1,000,000 ($500,000) limit. When the year's average acquisition balance is over the
    limit, the interest is scaled by limit / balance (Pub. 936's worksheet with average balances).
    Interest on home-equity debt not used for the home is not deductible.
    """
    federal = person.model.year_config.tax.federal
    share = 0.5 if person.filing_status == FilingStatus.MARRIED_FILING_SEPARATELY else 1.0
    debts = [home.mortgage for home in person.homes if getattr(home, "mortgage", None) is not None]
    debts += list(person.home_equity_lines)
    interest = acquisition = grandfathered = 0.0
    for debt in debts:
        debt_interest = debt.interest_paid_this_year
        if not debt_interest:
            continue
        average = debt.average_balance_this_year
        acq, old = debt.acquisition_split()
        interest += debt_interest * (acq / average if average > 0 else 1.0)
        acquisition += acq
        grandfathered += old
    if acquisition <= 0:
        return interest
    old_allowed = min(grandfathered, federal.mortgage_interest_grandfathered_debt_limit * share)
    new_limit = max(0.0, federal.mortgage_interest_debt_limit * share - old_allowed)
    allowed = old_allowed + min(acquisition - grandfathered, new_limit)
    if allowed < acquisition:
        interest *= allowed / acquisition
    return interest
