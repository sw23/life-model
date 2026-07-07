# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from enum import Enum
from typing import List, Optional

from ..base_classes import Investment
from ..model import Event, LifeModelAgent
from ..people.person import Person


class TrustType(Enum):
    REVOCABLE = "revocable"
    IRREVOCABLE = "irrevocable"


class Trust(LifeModelAgent):
    """A revocable or irrevocable trust holding an invested balance for named beneficiaries.

    The trust's balance grows with the economy (like an :class:`~life_model.base_classes.Investment`
    of the given asset class). The grantor moves cash in with :meth:`fund` and money reaches
    beneficiaries through :meth:`distribute`.

    Tax treatment (v1, deliberately minimal):

    * **Revocable** trusts are transparent: the balance counts in the grantor's gross estate
      (``Person._gross_estate_value``) and, at the grantor's death, pays out directly to the
      trust's surviving beneficiaries — outside the will/`_find_beneficiary` path.
    * **Irrevocable** trusts are excluded from the grantor's gross estate. Funding above the
      annual gift exclusion consumes the grantor's remaining unified estate-tax exemption
      (tracked on ``Person.estate_exemption_used``). At the grantor's death the trust survives
      with its own registry entry and keeps growing.

    Documented simplifications — aggressive by design, so do not over-trust the trust advantage:

    * Trust income is untaxed until distributed, and distributions are treated as tax-free basis
      to beneficiaries. Real non-grantor trusts pay **compressed trust brackets** (the top federal
      rate begins near ~$15k of retained income), which would *worsen* irrevocable-trust outcomes
      relative to this model.
    * No K-1 pass-through of distributable net income to beneficiaries.
    * No generation-skipping transfer (GST) tax.
    * The annual gift exclusion is applied per trust per year, not per donee.
    """

    # Apply growth before tax-unit settlement, matching Investment's step ordering.
    STEP_PRIORITY = {"step": -10}

    def __init__(
        self,
        grantor: Person,
        trust_type: TrustType,
        beneficiaries: List[Person],
        *,
        name: str = "Trust",
        balance: float = 0.0,
        growth_rate: Optional[float] = None,
        asset_class: str = "equity",
    ):
        """Create a trust.

        Args:
            grantor: The person who establishes (and funds) the trust.
            trust_type: ``TrustType.REVOCABLE`` or ``TrustType.IRREVOCABLE``.
            beneficiaries: The people the trust benefits.
            name: Display name for reports/events.
            balance: Initial trust corpus. Note: an initial balance is *not* treated as a gift;
                use :meth:`fund` to move money in with gift/exemption accounting.
            growth_rate: Explicit annual growth percentage; defers to the economy's return for
                ``asset_class`` when None.
            asset_class: ``"equity"`` (default), ``"bond"``, or ``"cash"``.
        """
        super().__init__(grantor.model)
        self.grantor = grantor
        self.trust_type = trust_type
        self.beneficiaries = list(beneficiaries)
        self.name = name
        self.balance = balance
        self._growth_rate_override = growth_rate
        if asset_class not in Investment._ASSET_CLASS_RATES:
            raise ValueError(
                f"Unknown asset_class {asset_class!r}; expected one of {list(Investment._ASSET_CLASS_RATES)}"
            )
        self.asset_class = asset_class
        # Gifts into the trust this calendar year (for the annual gift-exclusion accounting).
        self.contributions_this_year = 0.0
        self.stat_balance_history: List[float] = []

        self.model.registries.trusts.register(grantor, self)

    @property
    def growth_rate(self) -> float:
        """Annual growth rate (percent): the explicit override if set, else the economy's return."""
        if self._growth_rate_override is not None:
            return self._growth_rate_override
        rate_name = Investment._ASSET_CLASS_RATES[self.asset_class]
        return self.model.economy.rate(rate_name, self.model.year)

    def fund(self, amount: float) -> float:
        """Move cash from the grantor into the trust.

        For an irrevocable trust, the year's contributions above the annual gift exclusion
        consume the grantor's remaining unified estate-tax exemption
        (``grantor.estate_exemption_used``); a revocable trust is transparent, so funding it has
        no gift consequence.

        Args:
            amount: Amount to move in (limited by the grantor's available bank balance).

        Returns:
            float: The amount actually transferred.
        """
        if amount <= 0:
            return 0.0
        transferred = amount - self.grantor.deduct_from_bank_accounts(amount)
        if transferred <= 0:
            return 0.0
        self.balance += transferred

        if self.trust_type == TrustType.IRREVOCABLE:
            exclusion = self.model.tax_params_for_year(self.model.year).gift_exclusion
            prior_excess = max(0.0, self.contributions_this_year - exclusion)
            self.contributions_this_year += transferred
            new_excess = max(0.0, self.contributions_this_year - exclusion)
            if new_excess > prior_excess:
                self.grantor.estate_exemption_used += new_excess - prior_excess
        else:
            self.contributions_this_year += transferred
        return transferred

    def distribute(self, amount: float, beneficiary: Person) -> float:
        """Distribute cash from the trust to a beneficiary (tax-free basis, v1 simplification).

        Args:
            amount: Amount to distribute (limited by the trust balance).
            beneficiary: The person receiving the distribution.

        Returns:
            float: The amount actually distributed.
        """
        if amount <= 0 or beneficiary.is_deceased:
            return 0.0
        distributed = min(amount, self.balance)
        self.balance -= distributed
        beneficiary.receive_cash(distributed, source=f"distribution from {self.name}")
        return distributed

    def pay_out_at_grantor_death(self):
        """Terminate a revocable trust at the grantor's death: split the balance evenly among the
        surviving beneficiaries (outside the will's beneficiary path) and remove the trust."""
        survivors = [b for b in self.beneficiaries if not b.is_deceased]
        if survivors and self.balance > 0:
            share = self.balance / len(survivors)
            for beneficiary in survivors:
                beneficiary.receive_cash(share, source=f"payout of {self.name}")
                self.model.event_log.add(
                    Event(f"{self.name} paid ${share:,.0f} to {beneficiary.name} at {self.grantor.name}'s death")
                )
            self.balance = 0.0
        elif self.balance > 0:
            self.model.event_log.add(Event(f"{self.name} had no surviving beneficiaries; assets dissolved"))
        self.model.registries.trusts.unregister(self.grantor, self)
        self.remove()

    def step(self):
        """Apply the year's growth and track the balance."""
        self.balance += self.balance * (self.growth_rate / 100)
        self.stat_balance_history.append(self.balance)

    def post_step(self):
        self.contributions_this_year = 0.0

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Name: {html.escape(self.name)}</li>"
        desc += f"<li>Type: {self.trust_type.value}</li>"
        desc += f"<li>Grantor: {html.escape(self.grantor.name)}</li>"
        desc += f"<li>Beneficiaries: {html.escape(', '.join(b.name for b in self.beneficiaries))}</li>"
        desc += f"<li>Balance: ${self.balance:,.2f}</li>"
        desc += "</ul>"
        return desc
