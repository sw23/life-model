# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from typing import Optional

from ..base_classes import Loan
from ..model import Event, LifeModel, LifeModelAgent
from ..people.person import Person
from ..tax.federal import FilingStatus
from ..tax.income import IncomeType


class Home(LifeModelAgent):
    def __init__(
        self,
        person: Person,
        name: str,
        purchase_price: float,
        value_yearly_increase: float,
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
            value_yearly_increase (float): Percentage of yearly home value appreciation.
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
        self.value_yearly_increase = value_yearly_increase
        self.down_payment = down_payment
        self.mortgage = mortgage
        self.expenses = expenses
        self.expenses.home = self
        self.home_value: float = self.purchase_price

        # Cost basis for the §121 capital-gains calculation on sale: purchase price plus the
        # cumulative cost of improvements made while owned (home.py improvements were previously an
        # expense that never affected basis).
        self.cost_basis: float = self.purchase_price
        self.total_improvements: float = 0.0
        self.sold: bool = False

        # Bind the mortgage to this owner (a Mortgage is constructed before its Home, so it defers
        # agent registration until the Home adopts it).
        if self.mortgage is not None:
            self.mortgage._attach(person)

        # Register with the model registry
        self.model.registries.homes.register(person, self)

        if purchase:
            self.buy()

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
        """Withdraw the down payment and closing costs from the owner's accounts.

        Used when a home is purchased during the simulation (``purchase=True``). Any amount the
        accounts can't cover becomes debt on the owner.
        """
        closing_costs = self.purchase_price * (self.model.config.housing.closing_cost_percent / 100)
        cash_needed = self.down_payment + closing_costs
        shortfall = self.person.pay_bills(cash_needed)
        self.person.debt += shortfall
        self.model.event_log.add(
            Event(
                f"{self.person.name} bought {self.name} for ${self.purchase_price:,.0f} (down + closing "
                f"${cash_needed:,.0f})"
            )
        )

    def sell(self, selling_cost_percent: Optional[float] = None) -> float:
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
            # No dedicated long-term-capital-gains schedule exists yet (Plan 05); the taxable
            # excess is recognized as ordinary income as an approximation.
            self.person.income.add(IncomeType.ORDINARY, taxable_gain)

        net_proceeds = sale_price - selling_costs - mortgage_payoff
        if self.mortgage is not None:
            self.mortgage.principal = 0.0
            self.model.registries.mortgages.unregister(self.person, self.mortgage)
        if net_proceeds > 0:
            self.person.receive_cash(net_proceeds, source=f"sale of {self.name}")

        self.sold = True
        self.model.registries.homes.unregister(self.person, self)
        self.model.event_log.add(
            Event(
                f"{self.person.name} sold {self.name} for ${sale_price:,.0f} "
                f"(net ${net_proceeds:,.0f}, taxable gain ${taxable_gain:,.0f})"
            )
        )
        return net_proceeds

    def make_yearly_payment(self, extra_to_principal: float = 0) -> float:
        """Pay this year's housing costs: home expenses, PMI, and the mortgage.

        The mortgage amortizes internally as twelve monthly payments. Improvement spending accrues
        to the cost basis. Returns the total cash paid for housing this year.
        """
        if self.sold:
            return 0.0
        expenses_paid = self.expenses.get_yearly_spending()
        # Improvements add to the home's cost basis (they were previously a pure expense).
        self.total_improvements += self.expenses.improvement_amount
        pmi_paid = self._pmi_for_year()
        mortgage_paid = 0.0
        if self.mortgage is not None:
            mortgage_paid = self.mortgage.make_yearly_payment(self.mortgage.monthly_payment, extra_to_principal)
        return expenses_paid + pmi_paid + mortgage_paid

    def _repr_html_(self):
        monthly = self.mortgage.monthly_payment if self.mortgage is not None else 0.0
        return f"{html.escape(self.name)}, purchase price ${self.purchase_price:,}, " + f"monthly mortgage ${monthly:,}"

    def post_step(self):
        # Appreciate at year end (consume-then-advance): property tax for the year is assessed
        # on the beginning-of-year value during the step stage.
        if self.sold:
            return
        self.home_value += self.home_value * (self.value_yearly_increase / 100)


class HomeExpenses(LifeModelAgent):
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
        self.home: Optional[Home] = None

    def get_yearly_spending(self):
        spending_amount = 0
        if self.home is not None:
            spending_amount += self.home.home_value * (self.property_tax_percent / 100)
            spending_amount += self.home.home_value * (self.home_insurance_percent / 100)
        spending_amount += self.maintenance_amount + self.improvement_amount + self.hoa_amount
        return spending_amount

    def post_step(self):
        # Escalators run after the year's expenses have been paid (consume-then-advance).
        self.maintenance_amount += self.maintenance_amount * (self.maintenance_increase / 100)
        self.improvement_amount += self.improvement_amount * (self.improvement_increase / 100)
        self.hoa_amount += self.hoa_amount * (self.hoa_increase / 100)


# https://www.nerdwallet.com/mortgages/mortgage-calculator/calculate-mortgage-payment
# https://www.valuepenguin.com/mortgages/mortgage-payments-calculator
# https://www.investopedia.com/calculate-principal-and-interest-5211981
class Mortgage(Loan):
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
        principal: Optional[float] = None,
        monthly_payment: Optional[float] = None,
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

        # Interest actually charged this year, captured as the year is amortized so the itemized
        # mortgage-interest deduction isn't understated by reading the post-payment principal.
        self.interest_paid_this_year = self.get_interest_amount("year")

        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_balance_history = []

    def _attach(self, person: Person) -> None:
        """Bind this mortgage to its owner and register it as a model agent."""
        self.person = person
        LifeModelAgent.__init__(self, person.model)
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
