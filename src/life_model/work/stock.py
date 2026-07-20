# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Stock compensation: multi-year RSU grants that recognize income as they vest.

Grants are denominated in dollars, the way they are actually negotiated ("$400k over four years"),
and converted to a notional position at grant. After that the employee bears price risk: the plan
carries a synthetic price index that compounds at the equity return, and a vest slice is worth its
dollar value scaled by how the index has moved since the grant. Share counts are avoided entirely
because the model has no share price to quote them against.
"""

import html
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Sequence

from ..model import LifeModelAgent

if TYPE_CHECKING:
    from ..account.brokerage import BrokerageAccount
    from .job import Job


class VestingSchedule:
    """The fraction of a grant that vests in each year after the grant.

    Fractions are indexed from the grant year: ``fractions[0]`` vests one year after the grant,
    ``fractions[1]`` two years after, and so on. They must be non-negative and sum to 1.

    **Cliffs are not a parameter, deliberately.** At year granularity a one-year cliff and a
    quarterly no-cliff schedule are indistinguishable — both vest 25% of a four-year grant during
    the first year. Sub-year cliff forfeiture (leaving at month 11 and losing everything) is
    therefore not representable here.
    """

    #: Tolerance on the fractions summing to 1, so hand-written thirds are accepted.
    SUM_TOLERANCE = 1e-6

    def __init__(self, fractions: "Sequence[float]"):
        fractions = tuple(float(f) for f in fractions)
        if not fractions:
            raise ValueError("VestingSchedule requires at least one year of fractions")
        if any(f < 0 for f in fractions):
            raise ValueError(f"VestingSchedule fractions must be non-negative, got {fractions}")
        total = sum(fractions)
        if abs(total - 1.0) > self.SUM_TOLERANCE:
            raise ValueError(f"VestingSchedule fractions must sum to 1.0, got {total}")
        self.fractions = fractions

    def __len__(self) -> int:
        return len(self.fractions)

    def __repr__(self) -> str:
        return f"VestingSchedule({self.fractions})"

    def fraction_for_year(self, years_since_grant: int) -> float:
        """Fraction vesting ``years_since_grant`` years after the grant (0 outside the schedule)."""
        index = years_since_grant - 1
        if index < 0 or index >= len(self.fractions):
            return 0.0
        return self.fractions[index]

    @classmethod
    def even(cls, years: int) -> "VestingSchedule":
        """An even schedule over ``years`` years."""
        if years < 1:
            raise ValueError("VestingSchedule.even requires at least one year")
        return cls([1.0 / years] * years)

    @classmethod
    def four_year(cls) -> "VestingSchedule":
        """Even quarters over four years — the common tech-industry default."""
        return cls((0.25, 0.25, 0.25, 0.25))

    @classmethod
    def three_year(cls) -> "VestingSchedule":
        """Even thirds over three years."""
        return cls.even(3)

    @classmethod
    def front_loaded(cls) -> "VestingSchedule":
        """Weighted toward the early years, as sign-on grants often are."""
        return cls((0.40, 0.30, 0.20, 0.10))

    @classmethod
    def back_loaded(cls) -> "VestingSchedule":
        """Weighted toward the later years (the Amazon-style shape)."""
        return cls((0.05, 0.15, 0.40, 0.40))

    #: Presets addressable by name from configuration.
    PRESETS = {
        "four_year": "four_year",
        "three_year": "three_year",
        "front_loaded": "front_loaded",
        "back_loaded": "back_loaded",
    }

    @classmethod
    def from_name(cls, name: str, default_years: int = 4) -> "VestingSchedule":
        """Build a preset by name; ``"even"`` uses ``default_years``."""
        if name == "even":
            return cls.even(default_years)
        if name not in cls.PRESETS:
            raise ValueError(f"Unknown vesting schedule {name!r}; expected one of {sorted(cls.PRESETS)} or 'even'")
        return getattr(cls, cls.PRESETS[name])()


@dataclass
class StockGrant:
    """A single equity award, valued in dollars at the moment it was granted.

    Deliberately a plain value object rather than a ``LifeModelAgent``: a full career issues on the
    order of thirty grants per person, and every agent is walked three times a year by the model's
    step dispatch and again for each collected statistic. Grants carry no statistics of their own
    and need no step hooks, so the owning :class:`StockPlan` does all the work.
    """

    #: Dollar value of the award on the day it was granted.
    value_at_grant: float
    #: Simulated year the award was issued.
    grant_year: int
    #: How the award vests over the years following ``grant_year``.
    schedule: VestingSchedule
    #: Price index at grant, against which later vests are revalued.
    price_index_at_grant: float = 1.0
    #: Fractions already vested, so a partial career leaves the rest unrecognized.
    vested_fraction: float = field(default=0.0)

    def fraction_vesting_in(self, year: int) -> float:
        """Fraction of the award vesting in ``year``."""
        return self.schedule.fraction_for_year(year - self.grant_year)

    @property
    def unvested_fraction(self) -> float:
        return max(0.0, 1.0 - self.vested_fraction)


class StockPlan(LifeModelAgent):
    """The equity component of a job: issues grants, vests them, and recognizes the income.

    Attaches to a :class:`~life_model.work.job.Job` and sets the job's ``stock_plan``
    back-reference, the same way a 401k account attaches to a job.

    Three modeling choices worth stating outright:

    * **Vest income is W-2 wages** — ordinary income *and* full FICA wages, and Social Security
      credit for the year. That is what a real vest is.
    * **Vest income is excluded from 401(k)-eligible compensation**, the common plan-document
      treatment. This needs no code: ``Job.pre_step`` computes contributions off base salary alone.
    * **Withholding is not modeled.** Real vests withhold at the flat supplemental rate, which
      chronically under-withholds high earners. Because the simulation settles true annual
      liability at year end instead of tracking withholding, modeling it would net to zero while
      adding a spurious cash-timing artifact.

    Refreshers are a fixed dollar value grown at a constant rate. Real refreshers are re-sized
    against the current share price and a performance rating, which dampens both tails; that
    feedback is not modeled.
    """

    # Runs after Job.pre_step (priority 0) so wages are already on the ledger, and well before the
    # step stage where the tax unit reads it.
    STEP_PRIORITY = {"pre_step": 5}

    def __init__(
        self,
        job: "Job",
        *,
        signon_value: float = 0.0,
        refresher_value: float = 0.0,
        refresher_start_year: int = 1,
        refresher_growth_percent: float = 0.0,
        schedule: Optional[VestingSchedule] = None,
        signon_schedule: Optional[VestingSchedule] = None,
        disposition: str = "sell",
        growth_rate: Optional[float] = None,
        brokerage_account: "Optional[BrokerageAccount]" = None,
    ):
        """Stock compensation plan attached to a job.

        Args:
            job: The job this plan is part of.
            signon_value: Dollar value of a sign-on grant issued in the plan's first year.
            refresher_value: Dollar value of each annual refresher grant.
            refresher_start_year: Years after the plan starts before the first refresher is issued.
                Defaults to 1 (the first anniversary).
            refresher_growth_percent: Yearly percentage growth applied to ``refresher_value``.
            schedule: Vesting schedule for refresher grants. Defaults to the configured preset.
            signon_schedule: Vesting schedule for the sign-on grant. Defaults to ``schedule``.
            disposition: What happens to vested shares. ``"sell"`` (default) sells at vest, which
                realizes exactly zero capital gain because basis is fair market value at vest.
                ``"hold"`` deposits them into a brokerage account instead, where post-vest
                appreciation is taxed on eventual sale. Holding risks the entire position to save
                the rate spread on the *appreciation only* — the tax on the vest value itself is
                unavoidable either way.
            growth_rate: Annual percentage growth of the company's stock. Defers to the economy's
                equity return when None, which ties company stock to the broad market.
            brokerage_account: Where ``disposition="hold"`` deposits vested shares. Defaults to the
                owner's first brokerage account, resolved at vest time.
        """
        super().__init__(job.owner.model)
        if disposition not in ("sell", "hold"):
            raise ValueError(f"Unknown disposition {disposition!r}; expected 'sell' or 'hold'")

        self.job = job
        self.owner = job.owner
        self.disposition = disposition
        self._growth_rate_override = growth_rate
        self.brokerage_account = brokerage_account

        equity_config = self.model.config.equity_comp
        if schedule is None:
            schedule = VestingSchedule.from_name(equity_config.default_schedule, equity_config.default_vesting_years)
        self.schedule = schedule
        self.signon_schedule = signon_schedule if signon_schedule is not None else schedule

        self.refresher_value = refresher_value
        self.refresher_start_year = refresher_start_year
        self.refresher_growth_percent = refresher_growth_percent

        self.start_year = self.model.year
        # Compounds at the stock's return each year; a vest slice is revalued by how far the index
        # has moved since its grant.
        self.price_index = 1.0
        self.grants: List[StockGrant] = []

        self.stat_stock_vested = 0.0
        self.stat_stock_unvested = 0.0
        self.stat_gross_income = 0.0

        if signon_value > 0:
            self.grants.append(
                StockGrant(
                    value_at_grant=signon_value,
                    grant_year=self.start_year,
                    schedule=self.signon_schedule,
                    price_index_at_grant=self.price_index,
                )
            )

        job.stock_plan = self

    @property
    def growth_rate(self) -> float:
        """Annual growth rate (percent) of the company's stock."""
        if self._growth_rate_override is not None:
            return self._growth_rate_override
        return self.model.economy.equity_return(self.model.year)

    @growth_rate.setter
    def growth_rate(self, value: Optional[float]) -> None:
        self._growth_rate_override = value

    @property
    def unvested_value(self) -> float:
        """Current market value of everything not yet vested."""
        return sum(
            grant.value_at_grant * grant.unvested_fraction * (self.price_index / grant.price_index_at_grant)
            for grant in self.grants
        )

    def grant(self, value: float, schedule: Optional[VestingSchedule] = None) -> StockGrant:
        """Issue a grant of ``value`` dollars at the current price index."""
        new_grant = StockGrant(
            value_at_grant=value,
            grant_year=self.model.year,
            schedule=schedule if schedule is not None else self.schedule,
            price_index_at_grant=self.price_index,
        )
        self.grants.append(new_grant)
        return new_grant

    def pre_step(self):
        if self.job.retired:
            # Leaving forfeits everything unvested — the correct real-world outcome for a
            # departure, and it needs no bookkeeping beyond never recognizing the value.
            self.stat_stock_vested = 0.0
            self.stat_stock_unvested = 0.0
            self.stat_gross_income = 0.0
            return

        # Advance the price index first, so a grant issued this year is recorded at this year's
        # index and vests nothing until next year.
        self.price_index *= 1 + self.growth_rate / 100

        self._issue_refresher_if_due()
        vested = self._vest_current_year()

        if vested > 0:
            # A vest is W-2 compensation: ordinary income and FICA wages alike. Social Security
            # accumulates it into the year's record and re-clamps the total to the wage base, so
            # adding it on top of salary is safe.
            self.owner.income.add_wages(ordinary_amount=vested, fica_wages=vested)
            if self.owner.social_security is not None:
                self.owner.social_security.add_income_for_year(vested)
            self._dispose(vested)

        self.stat_stock_vested = vested
        self.stat_gross_income = vested
        self.stat_stock_unvested = self.unvested_value

    def _issue_refresher_if_due(self) -> None:
        """Issue this year's refresher grant, if the plan has reached the refresher schedule."""
        if self.refresher_value <= 0:
            return
        years_in = self.model.year - self.start_year
        if years_in < self.refresher_start_year:
            return
        growth = (1 + self.refresher_growth_percent / 100) ** (years_in - self.refresher_start_year)
        self.grant(self.refresher_value * growth)

    def _vest_current_year(self) -> float:
        """Vest every live grant's slice for this year and return the total market value."""
        total = 0.0
        for grant in self.grants:
            fraction = grant.fraction_vesting_in(self.model.year)
            if fraction <= 0:
                continue
            revaluation = self.price_index / grant.price_index_at_grant
            total += grant.value_at_grant * fraction * revaluation
            grant.vested_fraction += fraction
        return total

    def _dispose(self, vested: float) -> None:
        """Sell the vested shares for cash, or hold them in a taxable brokerage account.

        Selling at vest realizes exactly zero capital gain: basis is fair market value at vest, so
        the sale price and the basis are the same number. Holding creates a lot at that same basis,
        with a holding period starting now, so only post-vest appreciation is ever taxed as a gain.
        """
        if self.disposition == "sell":
            self.owner.receive_cash(vested, source="stock vest")
            return

        account = self.brokerage_account
        if account is None:
            accounts = self.owner.brokerage_accounts
            account = accounts[0] if accounts else None
        if account is None:
            # Nowhere to hold the shares; fall back to cash rather than losing the value.
            self.owner.receive_cash(vested, source="stock vest")
            return
        account.deposit_with_basis(vested, cost_basis=vested, acquired_year=self.model.year)

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.job.company)}</li>"
        desc += f"<li>Vested this year: ${self.stat_stock_vested:,.2f}</li>"
        desc += f"<li>Unvested: ${self.unvested_value:,.2f}</li>"
        desc += f"<li>Disposition: {html.escape(self.disposition)}</li>"
        desc += "</ul>"
        return desc
