# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, cast

from ..ledger import FlowKind
from ..model import Event, LifeModel, LifeModelAgent

if TYPE_CHECKING:
    from ..people.person import Person


class DonationType(Enum):
    """Enum for donation types"""

    CASH = "Cash"
    #: Appreciated long-term shares given in kind from the donor's brokerage accounts: deducted at fair
    #: market value (30%-of-AGI limit) with no capital gain; any part the accounts can't cover is cash.
    STOCK = "Stock"
    PROPERTY = "Property"
    OTHER = "Other"
    #: A qualified charitable distribution from the donor's traditional IRAs (70½+, up to the year's
    #: limit): excluded from income, counts toward the RMD, not deductible. Before 70½ (or without an
    #: IRA) it is given in cash.
    QCD = "Qualified charitable distribution"


class Donation(LifeModelAgent):
    """A recurring gift: the year's donation is made once a year, in the first month of the year,
    from the donor's bank (deductible on that year's return)."""

    STATS_OWNED = frozenset({"stat_charitable_donations"})

    # Donate in pre_step after the month's income is deposited (jobs run at the default priority 0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": 10}

    def __init__(
        self,
        person: "Person",
        charity_name: str,
        annual_amount: float,
        donation_type: DonationType = DonationType.CASH,
        tax_deductible: bool = True,
        frequency_years: int = 1,
        start_year: int | None = None,
        end_year: int | None = None,
    ):
        """Models a charitable donation for a person

        Args:
            person: The person making the donation
            charity_name: Name of the charity receiving the donation
            annual_amount: Amount to donate (per frequency_years)
            donation_type: Type of donation (cash, stock, property, etc.)
            tax_deductible: Whether the donation is tax deductible
            frequency_years: How often to make donation (1=yearly, 2=every 2 years, etc.)
            start_year: First year to make donation (defaults to current year)
            end_year: Last year to make donation (defaults to model end)
        """
        super().__init__(person.model)
        self.person = person
        self.charity_name = charity_name
        self.annual_amount = annual_amount
        self.donation_type = donation_type
        self.tax_deductible = tax_deductible
        self.frequency_years = frequency_years
        model = cast(LifeModel, person.model)
        self.start_year = start_year if start_year is not None else model.year
        self.end_year = end_year if end_year is not None else model.end_year

        # Track donation stats
        self.stat_charitable_donations = 0  # Donations made this year
        self.stat_total_donated = 0  # Total donated over lifetime
        #: This year's gift split by how it is deducted: cash (60% limit), appreciated long-term property
        #: at fair market value (30% limit), and a QCD (excluded from income instead).
        self.cash_given_this_year = 0.0
        self.property_given_this_year = 0.0
        self.qcd_this_year = 0.0
        self._qcd_year: int | None = None

        # Register with the model registry
        model.registries.donations.register(person, self)

    def should_donate_this_year(self) -> bool:
        """Check if a donation should be made this year"""
        model = cast(LifeModel, self.person.model)
        current_year = model.year
        if current_year < self.start_year or current_year > self.end_year:
            return False
        years_since_start = current_year - self.start_year
        return years_since_start % self.frequency_years == 0

    def make_donation(self) -> float:
        """Process donation payment from person's bank account

        Returns:
            Amount actually donated (may be less than requested if insufficient funds)
        """
        if not self.should_donate_this_year():
            return 0.0
        model = cast(LifeModel, self.person.model)
        if self.donation_type == DonationType.QCD and self._qcd_year == model.year:
            return self.qcd_this_year  # paid from the IRA ahead of its RMD (TraditionalIRA.pre_step)

        wanted = self.annual_amount
        given_in_kind = 0.0
        if self.donation_type == DonationType.STOCK:
            given_in_kind = self._give_shares(wanted)
            self.property_given_this_year = given_in_kind
        # The rest in cash. Note: deduct_from_bank_accounts returns the amount that COULD NOT be deducted.
        remaining_balance = self.person.deduct_from_bank_accounts(
            wanted - given_in_kind, kind=FlowKind.GIFT, sink=self.charity_name, cause="charitable donation"
        )
        cash = wanted - given_in_kind - remaining_balance
        self.cash_given_this_year = cash
        amount_withdrawn = cash + given_in_kind

        if amount_withdrawn > 0:
            self.stat_charitable_donations = amount_withdrawn
            self.stat_total_donated += amount_withdrawn

            # Log the donation event
            model = cast(LifeModel, self.person.model)
            model.event_log.add(Event(f"{self.person.name} donated ${amount_withdrawn:,.0f} to {self.charity_name}"))

        return amount_withdrawn

    def _give_shares(self, amount: float) -> float:
        """Transfer up to ``amount`` of long-term appreciated lots from the donor's brokerage accounts to
        the charity (no sale, so no gain). Returns the fair market value given."""
        given = 0.0
        for account in self.person.brokerage_accounts:
            if given >= amount:
                break
            value = account.transfer_long_term_in_kind(amount - given)
            if value > 0:
                self.person.model.ledger.post(
                    value,
                    FlowKind.GIFT,
                    from_account=account,
                    sink=self.charity_name,
                    cause="charitable donation of appreciated shares",
                    agent=self.person,
                )
                given += value
        return given

    def make_qcd(self, ira, room: float) -> float:
        """Pay this year's gift from ``ira`` as a qualified charitable distribution (called by the IRA's
        ``pre_step`` before it takes the RMD), up to ``room`` of the year's QCD limit."""
        model = cast(LifeModel, self.person.model)
        if self.donation_type != DonationType.QCD or not self.should_donate_this_year():
            return 0.0
        if self._qcd_year != model.year:
            self._qcd_year = model.year
            self.qcd_this_year = 0.0
            self.stat_charitable_donations = 0
        amount = min(self.annual_amount - self.qcd_this_year, room, ira.balance)
        if amount <= 0:
            return 0.0
        taken = ira.withdraw(amount)
        model.ledger.post(
            taken,
            FlowKind.GIFT,
            from_account=ira,
            sink=self.charity_name,
            cause="qualified charitable distribution",
            agent=self.person,
        )
        from ..tax.income import IncomeEntry, IncomeType

        # On Form 1040 line 4a (gross) but not 4b (taxable): a zero-amount entry carrying the gross.
        self.person.income.entries.append(
            IncomeEntry(IncomeType.PRETAX_DISTRIBUTION, 0.0, gross=taken, source="qcd", month=self.model.month)
        )
        self.qcd_this_year += taken
        self.stat_charitable_donations += taken
        self.stat_total_donated += taken
        return taken

    def get_tax_deduction_amount(self) -> float:
        """This year's deductible cash gift (QCDs are excluded from income instead; appreciated shares are
        :meth:`get_property_deduction_amount`)."""
        if not self.tax_deductible:
            return 0.0
        return self.cash_given_this_year

    def get_property_deduction_amount(self) -> float:
        """This year's gift of appreciated long-term shares, deductible at fair market value (30% limit)."""
        if not self.tax_deductible:
            return 0.0
        return self.property_given_this_year

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Charity: {html.escape(self.charity_name)}</li>"
        desc += f"<li>Annual Amount: ${self.annual_amount:,.2f}</li>"
        desc += f"<li>Type: {self.donation_type.value}</li>"
        desc += f"<li>Tax Deductible: {self.tax_deductible}</li>"
        desc += f"<li>Frequency: Every {self.frequency_years} year(s)</li>"
        desc += f"<li>Total Donated: ${self.stat_total_donated:,.2f}</li>"
        desc += "</ul>"
        return desc

    def pre_step(self):
        """Make this year's donation in the first month of the year (January, or the start month).

        Donations run in ``pre_step`` (after the month's income is deposited, priority 10); the
        charitable deduction is on the year's return, settled in December.
        """
        if not self.model.is_year_start:
            return
        # Reset this year's donation stat, then make the donation so the deduction is current. A QCD made
        # this year already ran (from the IRA, ahead of its RMD, in the year-start stage) and keeps its figures.
        year = self.person.model.year
        self.cash_given_this_year = 0.0
        self.property_given_this_year = 0.0
        if self._qcd_year != year:
            self.qcd_this_year = 0.0
            self.stat_charitable_donations = 0
        if self.person.is_deceased:
            # A pledge ends with its donor (an heir who inherits it re-owns it; see Person.die).
            return
        self.make_donation()

    def step(self):
        """No-op: donations are made in pre_step (the year's first month)."""

    def post_step(self):
        """No-op: donation cash movement happens in pre_step."""
