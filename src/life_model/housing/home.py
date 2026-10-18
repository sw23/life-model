# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import ClassVar

from ..base_classes import Loan
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

    def __init__(
        self,
        person: Person,
        name: str,
        purchase_price: float,
        value_yearly_increase: float | None,
        down_payment: float,
        mortgage: "Mortgage",
        expenses: "HomeExpenses",
        purchase: bool = False,
    ):
        """Home

        Args:
            person (Person): Primary resident or person that pays the bills.
            name (string): Name of the house or neighborhood.
            purchase_price (float): Purchase price of the home.
            value_yearly_increase (float): Percentage of yearly home value appreciation. Pass None to
                appreciate with the economy's home-appreciation rate each year.
            down_payment (float): Amount of down payment.
            mortgage (Mortgage): Mortgage associated with the home.
            expenses (HomeExpenses): Home expenses associated with the home.
            purchase (bool, optional): When True, the home is being bought now: the down payment
                and closing costs are withdrawn from the owner's accounts. Defaults to False (the
                home is already owned at the start of the simulation, so no cash changes hands).
        """
        super().__init__(person.model)
        self.person = person
        self.name = name
        self.purchase_price = purchase_price
        self._value_yearly_increase_override = value_yearly_increase
        self.down_payment = down_payment
        self.mortgage = mortgage
        self.expenses = expenses
        self.expenses.home = self
        self.home_value: float = self.purchase_price

        # Cost basis for the §121 capital-gains calculation on sale: purchase price plus the
        # cumulative cost of improvements made while owned.
        self.cost_basis: float = self.purchase_price
        self.total_improvements: float = 0.0
        self.sold: bool = False

        #: The last housing payment by line (see :meth:`make_monthly_payment` and
        #: :meth:`make_yearly_payment`).
        self.year_payment: dict[str, float] = {}

        # Bind the mortgage to this owner (a Mortgage is constructed before its Home, so it defers
        # agent registration until the Home adopts it).
        if self.mortgage is not None:
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
        """Property tax assessed for the year on the current home value (deductible as SALT)."""
        return self.home_value * (self.expenses.property_tax_percent / 100)

    @property
    def loan_to_value(self) -> float:
        """Loan-to-value ratio as a percentage of the original purchase price."""
        if self.mortgage is None or self.purchase_price <= 0:
            return 0.0
        return self.mortgage.principal / self.purchase_price * 100

    def _pmi_for_year(self) -> float:
        """Private mortgage insurance charged this year while LTV exceeds the threshold."""
        if self.mortgage is None or self.mortgage.principal <= 0:
            return 0.0
        housing = self.model.config.housing
        if self.loan_to_value > housing.pmi_ltv_threshold:
            return self.mortgage.principal * (housing.pmi_rate / 100)
        return 0.0

    def buy(self):
        """Withdraw the down payment and closing costs from the owner's household.

        Used when a home is purchased during the simulation (``purchase=True``). The cash comes
        through the household waterfall (:meth:`TaxUnit.pay_bills`): both spouses' banks, then
        brokerage, Roth basis, pre-tax accounts and the remaining Roth money; the gains, ordinary
        income and penalties it creates are taxed when the year settles. Any amount the household
        can't cover becomes debt on the owner.
        """
        from ..people.tax_unit import TaxUnit

        closing_costs = self.purchase_price * (self.model.config.housing.closing_cost_percent / 100)
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

        cost_basis = self.cost_basis + self.total_improvements
        gain = sale_price - selling_costs - cost_basis
        if self.person.filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
            exclusion = housing.section_121_exclusion.married_filing_jointly
        else:
            exclusion = housing.section_121_exclusion.single
        taxable_gain = max(0.0, gain - exclusion)
        if taxable_gain > 0:
            # A residence held long enough to qualify for §121 is by definition held over a year,
            # so the excess above the exclusion is always a long-term gain.
            self.person.income.add(IncomeType.LONG_TERM_CAPITAL_GAIN, taxable_gain, source="home_sale")

        net_proceeds = sale_price - selling_costs - mortgage_payoff
        ledger = self.model.ledger
        cause = f"sale of {self.name}"
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
    # Escalators at year end, after the year's taxes (0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 10}

    def __init__(
        self,
        model: LifeModel,
        property_tax_percent: float,
        home_insurance_percent: float,
        maintenance_amount: float,
        maintenance_increase: float,
        improvement_amount: float,
        improvement_increase: float,
        hoa_amount: float,
        hoa_increase: float,
    ):
        """Home Expenses

        Args:
            property_tax_percent (float): Property tax percentage paid yearly based on home value.
            home_insurance_percent (float): Yearly home insurance cost as percentage of home value.
            maintenance_amount (float): Yearly cost of home maintenance.
            maintenance_increase (float): Yearly percentage increase of maintenance costs.
            improvement_amount (float): Yearly cost of improvements.
            improvement_increase (float): Yearly percentage increase of improvment costs.
            hoa_amount (float): Yearly HOA dues.
            hoa_increase (float): Yearly percentage incresae of HOA dues.
        """
        super().__init__(model)
        self.property_tax_percent = property_tax_percent
        self.home_insurance_percent = home_insurance_percent
        self.maintenance_amount = maintenance_amount
        self.maintenance_increase = maintenance_increase
        self.improvement_amount = improvement_amount
        self.improvement_increase = improvement_increase
        self.hoa_amount = hoa_amount
        self.hoa_increase = hoa_increase
        self.home: Home | None = None

    def get_yearly_spending(self):
        spending_amount = 0
        if self.home is not None:
            spending_amount += self.home.home_value * (self.property_tax_percent / 100)
            spending_amount += self.home.home_value * (self.home_insurance_percent / 100)
        spending_amount += self.maintenance_amount + self.improvement_amount + self.hoa_amount
        return spending_amount

    def year_lines(self) -> dict[str, float]:
        """:meth:`get_yearly_spending` by line (property tax, insurance, maintenance, improvements, HOA)."""
        lines = {}
        if self.home is not None:
            lines["property_tax"] = self.home.home_value * (self.property_tax_percent / 100)
            lines["home_insurance"] = self.home.home_value * (self.home_insurance_percent / 100)
        lines["maintenance"] = self.maintenance_amount
        lines["improvements"] = self.improvement_amount
        lines["hoa"] = self.hoa_amount
        return {name: amount for name, amount in lines.items() if amount}

    def on_year_end(self):
        # Escalators run after the year's expenses have been paid (consume-then-advance).
        self.maintenance_amount += self.maintenance_amount * (self.maintenance_increase / 100)
        self.improvement_amount += self.improvement_amount * (self.improvement_increase / 100)
        self.hoa_amount += self.hoa_amount * (self.hoa_increase / 100)


# https://www.nerdwallet.com/mortgages/mortgage-calculator/calculate-mortgage-payment
# https://www.valuepenguin.com/mortgages/mortgage-payments-calculator
# https://www.investopedia.com/calculate-principal-and-interest-5211981
class Mortgage(Loan):
    STATS_OWNED = frozenset({"stat_mortgage_principal"})

    """A home mortgage.

    A Mortgage is an amortizing :class:`~life_model.base_classes.Loan`, so it shares the ABC's
    monthly amortization (with clamps and a zero-rate guard) instead of its own annual
    simple-interest formula. Because a Mortgage is constructed *before* its :class:`Home` (which
    supplies the owning person/model), it initializes its loan data eagerly and defers agent
    registration until the Home adopts it via :meth:`_attach`.
    """

    def __init__(
        self,
        loan_amount: float,
        start_date: float,
        length_years: int,
        yearly_interest_rate: float,
        principal: float | None = None,
        monthly_payment: float | None = None,
    ):
        """Mortgage

        Args:
            loan_amount (float): Amount of loan.
            start_date (float): Starting year of loan.
            length_years (int): Length of years of loan (e.g. 30, 15)
            yearly_interest_rate (float): Yearly interest rate
            principal (float, optional): Initial principal. Defaults to None.
            monthly_payment (float, optional): Monthly payment. Defaults to None.
        """
        # Intentionally does NOT call Loan.__init__ (no person/model yet); initialize the loan
        # data directly and register as an agent later in _attach.
        self.person = None
        self.loan_amount = loan_amount
        self.start_date = start_date
        self.length_years = length_years
        self.yearly_interest_rate = yearly_interest_rate
        self.principal = loan_amount if principal is None else principal
        self.monthly_payment = self.calculate_monthly_payment() if monthly_payment is None else monthly_payment

        # Interest charged this year, accumulated payment by payment from each year start (the
        # itemized mortgage-interest deduction reads it). Until the first year starts it holds the
        # year's simple-interest estimate; a mortgage taken out mid-run starts at zero (_attach).
        self.interest_paid_this_year = self.get_interest_for_year()
        self._principal_paid_this_year = 0.0

        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []
        self.stat_yearly_principal_payment_history = []
        self.stat_yearly_interest_payment_history = []

    def collect_stats(self):
        self.stat_mortgage_principal = 0.0 if self.person.is_deceased else self.principal

    def _attach(self, person: Person) -> None:
        """Bind this mortgage to its owner and register it as a model agent."""
        self.person = person
        LifeModelAgent.__init__(self, person.model)
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
