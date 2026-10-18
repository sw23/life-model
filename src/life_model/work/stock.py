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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
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
    PRESETS: ClassVar[dict[str, str]] = {
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
    #: The last year whose vest has happened (an existing grant's vests before the simulation started).
    vested_through_year: int | None = None
    #: An existing grant's current market value of its unvested part (from the equity statement): sets
    #: ``price_index_at_grant`` so the unvested shares are worth that now (Plan 27 D1). None keeps the
    #: grant valued at its grant value.
    unvested_value: float | None = None

    def fraction_vesting_in(self, year: int) -> float:
        """Fraction of the award vesting in ``year``."""
        return self.schedule.fraction_for_year(year - self.grant_year)

    @property
    def unvested_fraction(self) -> float:
        return max(0.0, 1.0 - self.vested_fraction)


#: IRC §423(b)(8): at most $25,000 of stock (valued when the option is granted, the offering date) may
#: accrue per calendar year under an employee stock purchase plan.
# vintage: statutory, source: 26 U.S.C. §423(b)(8) (Cornell LII, fetched 2026-10-18)
ESPP_ANNUAL_LIMIT = 25_000.0
#: IRC §423(b)(6): the purchase price may be no less than 85% of fair market value (a 15% discount).
# vintage: statutory, source: 26 U.S.C. §423(b)(6)
ESPP_MAX_DISCOUNT_PCT = 15.0


@dataclass
class ESPP:
    """An employee stock purchase plan (IRC §423) attached to a :class:`StockPlan` (Plan 27 D3).

    ``contribution_pct`` of each month's gross pay is set aside after tax and buys company stock at the
    end of each offering period (``purchase_months``, default June and December) at ``discount_pct`` off the
    price then (with ``lookback``, off the lower of the offering-start and purchase prices), within the
    §423(b)(8) $25,000-a-year limit. The discount (fair market value less the price paid) is ordinary
    compensation income on the W-2, not FICA wages (§3121(a)(22)): the plan models every sale as a
    disqualifying disposition. ``disposition="sell"`` sells at purchase (the cash, contributions plus the
    discount, lands in the bank); ``"hold"`` keeps the shares in the plan's brokerage account at a basis of
    their market value. Simplification: the contributions leave the bank at the purchase, not out of each
    paycheck.
    """

    contribution_pct: float
    discount_pct: float = ESPP_MAX_DISCOUNT_PCT
    purchase_months: tuple[int, ...] = (6, 12)
    lookback: bool = False
    disposition: str = "sell"

    def __post_init__(self):
        if not 0 <= self.contribution_pct <= 100:
            raise ValueError("ESPP contribution_pct must be 0-100")
        if not 0 <= self.discount_pct <= ESPP_MAX_DISCOUNT_PCT:
            raise ValueError(f"ESPP discount_pct must be 0-{ESPP_MAX_DISCOUNT_PCT:g} (IRC §423(b)(6))")
        if self.disposition not in ("sell", "hold"):
            raise ValueError("ESPP disposition must be 'sell' or 'hold'")
        months = tuple(sorted({int(m) for m in self.purchase_months}))
        if not months or any(not 1 <= m <= 12 for m in months):
            raise ValueError("ESPP purchase_months must be months 1-12")
        object.__setattr__(self, "purchase_months", months)


@dataclass
class StockOption:
    """A stock option grant the owner exercises in a planned year (Plan 31; dollars, like grants).

    ``value`` is the market value of the option's shares at the plan's start (price index 1.0); it is
    revalued by the plan's price index to the exercise year. ``exercise_cost`` is the strike price times
    the shares. At exercise:

    * an **NSO**'s spread (value - cost) is W-2 wages (income tax and FICA);
    * an **ISO** exercised and held has no regular income: the spread is an AMT adjustment (Form 6251
      line 2i), which can create AMT and, later, the minimum tax credit (Form 8801);
    * ``sell_at_exercise=True`` is a cashless same-day sale: for an ISO that is a disqualifying
      disposition, so the spread is ordinary wages without FICA and no AMT adjustment arises.

    Held shares go to the plan's brokerage account (else the owner's first) as a lot with basis equal
    to the cost (ISO) or the value (NSO), acquired in the exercise year; the exercise cost is paid
    through the household waterfall. Simplifications: a held ISO lot is later sold by the waterfall like
    any lot (a sale within the holding periods is not re-characterized as a disqualifying disposition),
    and the ISO's higher AMT basis (a negative adjustment when the shares are sold) is not tracked.
    """

    kind: str
    exercise_year: int
    exercise_cost: float
    value: float
    sell_at_exercise: bool = False
    exercised: bool = field(default=False)

    def __post_init__(self):
        if self.kind not in ("iso", "nso"):
            raise ValueError(f"StockOption kind must be 'iso' or 'nso', got {self.kind!r}")
        if self.exercise_cost < 0 or self.value < 0:
            raise ValueError("StockOption exercise_cost and value must be non-negative")


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

    STATS_OWNED = frozenset({"stat_gross_income", "stat_stock_vested", "stat_stock_unvested"})

    # Runs after Job.pre_step (priority 0) so wages are already on the ledger. Vests happen once a
    # year, in the first month of the year (quarterly vesting is a later plan's).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": 5}

    @deprecated_arguments({"refresher_growth_percent": "refresher_growth_pct", "growth_rate": "growth_pct"})
    def __init__(
        self,
        job: "Job",
        *,
        signon_value: float = 0.0,
        refresher_value: float = 0.0,
        refresher_start_year: int = 1,
        refresher_growth_pct: float = 0.0,
        schedule: VestingSchedule | None = None,
        signon_schedule: VestingSchedule | None = None,
        disposition: str = "sell",
        growth_pct: float | None = None,
        brokerage_account: "BrokerageAccount | None" = None,
        options: "Sequence[StockOption] | None" = None,
        existing_grants: "Sequence[StockGrant] | None" = None,
        espp: "ESPP | None" = None,
    ):
        """Stock compensation plan attached to a job.

        Args:
            job: The job this plan is part of.
            signon_value: Dollar value of a sign-on grant issued in the plan's first year.
            refresher_value: Dollar value of each annual refresher grant.
            refresher_start_year: Years after the plan starts before the first refresher is issued.
                Defaults to 1 (the first anniversary).
            refresher_growth_pct: Yearly percentage growth applied to ``refresher_value`` (deprecated alias
                ``refresher_growth_percent``).
            schedule: Vesting schedule for refresher grants. Defaults to the configured preset.
            signon_schedule: Vesting schedule for the sign-on grant. Defaults to ``schedule``.
            disposition: What happens to vested shares. ``"sell"`` (default) sells at vest, which
                realizes exactly zero capital gain because basis is fair market value at vest.
                ``"hold"`` deposits them into a brokerage account instead, where post-vest
                appreciation is taxed on eventual sale. Holding risks the entire position to save
                the rate spread on the *appreciation only* — the tax on the vest value itself is
                unavoidable either way.
            growth_pct: Annual percentage growth of the company's stock (deprecated alias ``growth_rate``).
                Defers to the economy's equity return when None, which ties company stock to the broad
                market.
            brokerage_account: Where ``disposition="hold"`` deposits vested shares. Defaults to the
                owner's first brokerage account, resolved at vest time.
            options: Stock options (ISO / NSO) to exercise in planned years (:class:`StockOption`).
            existing_grants: Grants made before the simulation started that still have unvested shares
                (:class:`StockGrant` with its real ``grant_year``; Plan 27 D1). The vests before the start
                are taken as done, and ``unvested_value`` (the statement's current value of the unvested
                shares) revalues the grant.
            espp: An employee stock purchase plan (:class:`ESPP`).
        """
        refresher_growth_percent = refresher_growth_pct
        growth_rate = growth_pct
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
        self.grants: list[StockGrant] = []
        self.options: list[StockOption] = list(options or [])

        self.stat_stock_vested = 0.0
        self.stat_stock_unvested = 0.0
        self.stat_gross_income = 0.0

        for grant in existing_grants or ():
            self._add_existing_grant(grant)
        self.espp = espp
        if espp is not None and job.kind != "w2":
            raise ValueError("an ESPP is for W-2 jobs")
        # ESPP: pay set aside since the last purchase, the offering-start price index, and the year's
        # §423(b)(8) usage (stock value at the offering date).
        self._espp_pay = 0.0
        self._espp_offering_index = self.price_index
        self._espp_year_usage: tuple[int, float] = (self.model.year, 0.0)
        #: ESPP discount income recognized so far (all years).
        self.espp_discount_total = 0.0

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

    def _add_existing_grant(self, grant: StockGrant) -> None:
        """Add a grant made before the simulation started (see ``existing_grants``)."""
        start_year = self.model.year
        if grant.vested_through_year is None:
            # Vests happen in January; a run starting later in the year has had this year's vest.
            through = start_year - 1 if self.model.month == 1 else start_year
            grant.vested_through_year = through
            if grant.vested_fraction == 0:
                grant.vested_fraction = sum(
                    grant.schedule.fraction_for_year(year - grant.grant_year)
                    for year in range(grant.grant_year + 1, through + 1)
                )
        if grant.unvested_value is not None:
            unvested = grant.value_at_grant * grant.unvested_fraction
            if grant.unvested_value <= 0 or unvested <= 0:
                raise ValueError("an existing grant's unvested_value and unvested part must be positive")
            # Worth unvested_value at the plan's current price index (1.0 at the start).
            grant.price_index_at_grant = self.price_index * unvested / grant.unvested_value
        self.grants.append(grant)

    @property
    def growth_rate(self) -> float:
        """Annual growth rate (percent) of the company's stock."""
        if self._growth_rate_override is not None:
            return self._growth_rate_override
        return self.model.economy.equity_return(self.model.year)

    @growth_rate.setter
    def growth_rate(self, value: float | None) -> None:
        self._growth_rate_override = value

    @property
    def unvested_value(self) -> float:
        """Current market value of everything not yet vested."""
        return sum(
            grant.value_at_grant * grant.unvested_fraction * (self.price_index / grant.price_index_at_grant)
            for grant in self.grants
        )

    def grant(self, value: float, schedule: VestingSchedule | None = None) -> StockGrant:
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
        if self.espp is not None:
            self._espp_month()
        if not self.model.is_year_start:
            return
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
        self._exercise_options()
        vested = self._vest_current_year()

        if vested > 0:
            # A vest is W-2 compensation: ordinary income and FICA wages alike. Social Security
            # accumulates it into the year's record and re-clamps the total to the wage base, so
            # adding it on top of salary is safe.
            self.owner.income.add_wages(ordinary_amount=vested, fica_wages=vested, source="rsu_vest")
            if self.owner.social_security is not None:
                self.owner.social_security.add_income_for_year(vested)
            self._dispose(vested)

        self.stat_stock_vested = vested
        self.stat_gross_income = vested
        self.stat_stock_unvested = self.unvested_value

    def _exercise_options(self) -> None:
        """Exercise the options planned for this year (see :class:`StockOption`)."""
        from ..people.tax_unit import TaxUnit

        owner = self.owner
        company = self.job.company
        for option in self.options:
            if option.exercised or option.exercise_year != self.model.year:
                continue
            option.exercised = True
            value = option.value * self.price_index
            spread = max(0.0, value - option.exercise_cost)
            account = self.brokerage_account
            if account is None and owner.brokerage_accounts:
                account = owner.brokerage_accounts[0]
            cashless = option.sell_at_exercise or account is None
            if option.kind == "nso":
                owner.income.add_wages(ordinary_amount=spread, fica_wages=spread, source="nso_exercise")
                if owner.social_security is not None:
                    owner.social_security.add_income_for_year(spread)
            elif cashless:
                # Disqualifying disposition: compensation income on the W-2, not FICA wages.
                owner.income.add_wages(ordinary_amount=spread, fica_wages=0.0, source="iso_disqualifying")
            else:
                owner.income.add_amt_adjustment(spread, source="iso")
            if cashless:
                owner.receive_cash(
                    spread, source=company, kind=FlowKind.VEST, cause=f"{option.kind.upper()} exercise and sale"
                )
                continue
            unit = TaxUnit.for_member(owner)
            shortfall = unit.pay_bills(
                option.exercise_cost,
                kind=FlowKind.TRANSFER,
                cause=f"{option.kind.upper()} exercise cost",
                to_account=account,
            )
            if shortfall > 0:
                owner.add_debt(shortfall, to_account=account, cause=f"{option.kind.upper()} exercise cost")
            basis = option.exercise_cost if option.kind == "iso" else value
            account.deposit_with_basis(value, cost_basis=basis, acquired_year=self.model.year)
            self.model.ledger.post(
                spread,
                FlowKind.VEST,
                to_account=account,
                source=company,
                cause=f"{option.kind.upper()} exercise spread (held)",
                agent=owner,
            )

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
            if grant.vested_through_year is not None and grant.vested_through_year >= self.model.year:
                continue
            fraction = grant.fraction_vesting_in(self.model.year)
            grant.vested_through_year = self.model.year
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
        company = self.job.company
        if self.disposition == "sell":
            self.owner.receive_cash(vested, source=company, kind=FlowKind.VEST, cause="RSU vest (sold at vest)")
            return

        account = self.brokerage_account
        if account is None:
            accounts = self.owner.brokerage_accounts
            account = accounts[0] if accounts else None
        if account is None:
            # Nowhere to hold the shares; fall back to cash rather than losing the value.
            self.owner.receive_cash(vested, source=company, kind=FlowKind.VEST, cause="RSU vest (no brokerage)")
            return
        account.deposit_with_basis(vested, cost_basis=vested)
        self.model.ledger.post(
            vested, FlowKind.VEST, to_account=account, source=company, cause="RSU vest (held)", agent=self.owner
        )

    # --- ESPP ---

    def _current_price_index(self) -> float:
        """The stock's price index this month (the index advances at each year start; within the year it
        is interpolated at the stock's monthly rate)."""
        months = self.model.month - 1
        return self.price_index * (1 + self.growth_rate / 100) ** (months / 12)

    def _espp_month(self) -> None:
        """Set aside this month's ESPP contribution and buy at the end of an offering period."""
        espp = self.espp
        job = self.job
        if job.retired:
            self._espp_pay = 0.0
            return
        booked = job._booked_this_month()
        if booked is not None:
            self._espp_pay += booked.gross * espp.contribution_pct / 100
        if self.model.month in espp.purchase_months and self._espp_pay > 0:
            self._espp_purchase()

    def _espp_purchase(self) -> None:
        espp = self.espp
        owner = self.owner
        year = self.model.year
        now = self._current_price_index()
        start = self._espp_offering_index
        price = (min(start, now) if espp.lookback else now) * (1 - espp.discount_pct / 100)
        contributions = min(self._espp_pay, owner.spendable_bank_balance)
        self._espp_pay = 0.0
        self._espp_offering_index = now
        if price <= 0 or contributions <= 0:
            return
        # §423(b)(8): stock valued at the offering date, at most $25,000 a calendar year.
        used_year, used = self._espp_year_usage
        used = used if used_year == year else 0.0
        offering_value = contributions * start / price
        if used + offering_value > ESPP_ANNUAL_LIMIT:
            contributions *= max(0.0, ESPP_ANNUAL_LIMIT - used) / offering_value
            offering_value = contributions * start / price
        self._espp_year_usage = (year, used + offering_value)
        if contributions <= 0:
            return
        market_value = contributions * now / price
        discount = market_value - contributions
        company = self.job.company
        # A disqualifying disposition: the discount is compensation on the W-2, not FICA wages (§3121(a)(22)).
        owner.income.add_wages(ordinary_amount=discount, fica_wages=0.0, source="espp")
        self.espp_discount_total += discount
        self.stat_gross_income += discount
        account = self.brokerage_account
        if account is None and owner.brokerage_accounts:
            account = owner.brokerage_accounts[0]
        if espp.disposition == "sell" or account is None:
            owner.receive_cash(discount, source=company, kind=FlowKind.VEST, cause="ESPP purchase and sale (discount)")
            return
        shortfall = owner.deduct_from_bank_accounts(
            contributions, kind=FlowKind.TRANSFER, to_account=account, cause="ESPP purchase"
        )
        paid = contributions - shortfall
        account.deposit_with_basis(paid * now / price, cost_basis=paid * now / price)
        self.model.ledger.post(
            paid * now / price - paid,
            FlowKind.VEST,
            to_account=account,
            source=company,
            cause="ESPP purchase discount (held)",
            agent=owner,
        )

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.job.company)}</li>"
        desc += f"<li>Vested this year: ${self.stat_stock_vested:,.2f}</li>"
        desc += f"<li>Unvested: ${self.unvested_value:,.2f}</li>"
        desc += f"<li>Disposition: {html.escape(self.disposition)}</li>"
        desc += "</ul>"
        return desc
