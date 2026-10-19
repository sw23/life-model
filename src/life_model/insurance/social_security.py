# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

# The Social Security Administration uses a complex formula to calculate your
# Social Security benefits. Here's a simplified version of how it works:

# Calculate Your Average Indexed Monthly Earnings (AIME): The Social Security
# Administration takes your 35 highest-earning years (adjusted for inflation),
# adds them up, and then divides by the total number of months in those years
# to get your AIME.

# Apply the Bend Point Formula: The Social Security Administration then applies
# a formula to your AIME to calculate your Primary Insurance Amount (PIA). As
# of 2021, the formula is:

# 90% of the first $996 of your AIME, plus
# 32% of your AIME over $996 and up to $6,002, plus
# 15% of your AIME over $6,002
# The dollar amounts in the formula (known as "bend points") are adjusted each
# year for inflation.

# Adjust for Early or Late Retirement: If you start taking benefits before your
# full retirement age (which depends on your birth year), your monthly benefit
# will be reduced. If you delay taking benefits past your full retirement age,
# your monthly benefit will be increased.

# Cost-of-Living Adjustments (COLAs): Once you start receiving benefits, they
# will be adjusted each year for inflation based on the Consumer Price Index for
# Urban Wage Earners and Clerical Workers (CPI-W).

# The Social Security Administration has a more detailed explanation of how
# benefits are calculated.

# https://www.ssa.gov/oact/cola/piaformula.html
# https://www.ssa.gov/oact/cola/Benefits.html
# https://www.ssa.gov/oact/cola/latestCOLA.html
# https://www.ssa.gov/OACT/COLA/awiseries.html


from typing import TYPE_CHECKING, ClassVar

from ..config.financial_config import resolve_financial_config as _fin
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..model import Event, LifeModelAgent, snap_money
from ..people.person import Person
from ..tax.federal import FilingStatus

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig
    from ..economy import EconomyModel


def _realized_rate(economy: "EconomyModel | None", name: str, year: int, fallback: float) -> float:
    """The economy's realized ``name`` rate for ``year`` when that year has been simulated
    (start year through the current year), else the configured long-run ``fallback``.

    Projecting with only realized rates keeps a stochastic economy from being sampled ahead of the
    simulation (which would peek at future outcomes and reorder the shared random stream).
    """
    if economy is not None and economy.model.start_year <= year <= economy.model.year:
        return economy.rate(name, year)
    return fallback


def taxable_social_security(
    benefits: float, other_income: float, filing_status: FilingStatus, config: "FinancialConfig | None" = None
) -> float:
    """Taxable portion of a return's Social Security ``benefits`` (IRC §86, IRS Pub. 915 worksheet).

    Args:
        benefits: Gross benefits on the return (both spouses on a joint return).
        other_income: Modified AGI excluding Social Security: ordinary and preferential income plus
            tax-exempt interest.
        filing_status: The return's filing status (head of household uses the single thresholds).
        config: Per-model config. Defaults to the packaged defaults.

    Returns:
        The taxable amount, rounded to the cent: 0 below the lower base amount, 50% of the excess
        between the bases, 85% above the upper base, never more than 85% of the benefits.
    """
    if benefits <= 0:
        return 0.0

    bt = _fin(config).social_security.benefit_taxation
    if filing_status == FilingStatus.MARRIED_FILING_JOINTLY:
        lower = bt.lower_threshold_married_filing_jointly
        upper = bt.upper_threshold_married_filing_jointly
    elif filing_status == FilingStatus.MARRIED_FILING_SEPARATELY:
        lower = bt.lower_threshold_married_filing_separately
        upper = bt.upper_threshold_married_filing_separately
    else:
        lower = bt.lower_threshold_single
        upper = bt.upper_threshold_single

    provisional = other_income + bt.lower_inclusion_rate * benefits
    if provisional <= lower:
        return 0.0

    lower_band_taxable = bt.lower_inclusion_rate * min(benefits, provisional - lower)
    if provisional <= upper:
        return round(lower_band_taxable, 2)

    # Above the upper threshold: the lower band is capped at half the (upper-lower) spread.
    capped_lower_band = bt.lower_inclusion_rate * min(benefits, upper - lower)
    taxable = bt.upper_inclusion_rate * (provisional - upper) + capped_lower_band
    taxable = min(taxable, bt.upper_inclusion_rate * benefits)
    return round(taxable, 2)


def get_avg_wage_index(
    year: int, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> float:
    """Compute the average wage index for a given year

    Args:
        year: The year to compute the average wage index for
        config: Per-model config. Defaults to the packaged defaults.
        economy: The model's economy. Years after the published table grow by its realized wage
            growth; without it (or for unrealized years) by the configured long-run increase.

    Returns:
        The average wage index for the given year

    Raises:
        ValueError: If the year is before 1951
    """
    if year < 1951:
        raise ValueError("Average wage index is not available before 1951")

    ss_config = _fin(config).social_security
    last_year = ss_config.last_avg_wage_index_year

    if year <= last_year:
        # Years in this range are in the table
        return ss_config.avg_wage_index[year]
    else:
        # Years after this range are projected
        last_index = ss_config.avg_wage_index[last_year]
        for projected_year in range(last_year + 1, year + 1):
            growth = _realized_rate(economy, "wage_growth", projected_year, ss_config.last_avg_wage_index_increase)
            last_index *= 1 + growth / 100.0
        return last_index


def get_cost_of_living_adj(
    year: int, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> float:
    """Get the cost of living adjustment for a given year

    Args:
        year: The year to get the cost of living adjustment for
        config: Per-model config. Defaults to the packaged defaults.
        economy: The model's economy. Years after the published table use its realized inflation
            (the COLA tracks CPI-W); without it (or for unrealized years) the long-run assumption.

    Returns:
        The cost of living adjustment for the given year

    Raises:
        ValueError: If the year is before 1975
    """
    if year < 1975:
        raise ValueError("Cost of living adjustment is not available before 1975")

    ss_config = _fin(config).social_security
    last_year = ss_config.last_cost_of_living_adj_year

    if year <= last_year:
        # Years in this range are in the table
        return ss_config.cost_of_living_adj[year]
    else:
        # Years after this range follow realized inflation, else the long-run assumption.
        return _realized_rate(economy, "inflation", year, ss_config.long_run_cost_of_living_adj)


def get_bend_points(
    year: int, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> tuple[float, float]:
    """Get the bend points for a given year

    Args:
        year: The year to get the bend points for
        config: Per-model config. Defaults to the packaged defaults.
        economy: The model's economy. When given, bend points after the published table follow the
            statutory rule, scaling with the average wage index two years earlier (projected with
            the economy's realized wage growth); otherwise the configured long-run increase applies.

    Returns:
        A tuple containing the bend points for the given year

    Raises:
        ValueError: If the year is before 1979
    """
    if year < 1979:
        raise ValueError("Bend points are not available before 1979")

    ss_config = _fin(config).social_security
    last_year = ss_config.last_bend_points_year

    if year <= last_year:
        # Years in this range are in the table
        bend_point_data = ss_config.bend_points[year]
        return (float(bend_point_data[0]), float(bend_point_data[1]))
    else:
        bend_point_data = ss_config.bend_points[last_year]
        bp0, bp1 = float(bend_point_data[0]), float(bend_point_data[1])
        if economy is not None:
            # 42 U.S.C. 415(a)(1)(B): bend points scale with AWI(year - 2).
            ratio = get_avg_wage_index(year - 2, config, economy=economy) / get_avg_wage_index(
                last_year - 2, config, economy=economy
            )
            return (bp0 * ratio, bp1 * ratio)
        # Without an economy, grow the last published bend points by the configured long-run
        # increase. A 0% increase freezes them at the last published year.
        rate = ss_config.long_run_bend_point_increase / 100.0
        for _ in range(last_year, year):
            bp0 *= 1 + rate
            bp1 *= 1 + rate
        return (bp0, bp1)


def get_qc_earnings_for_year(
    year: int, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> int:
    """Compute the number of credits earned for a given year

    Args:
        year: The year to compute the number of credits earned for
        config: Per-model config. Defaults to the packaged defaults.

    Returns:
        The number of credits earned for the given year

    Raises:
        ValueError: If the year is before 1978
    """
    if year < 1978:
        raise ValueError("QC earnings are not available before 1978")

    ss_config = _fin(config).social_security
    credit_amt_1978 = ss_config.qc_credit_amount_1978
    avg_wage_idx_1976 = ss_config.qc_avg_wage_index_1976

    # Calculate previous year's QC amount (rounded to nearest 10 dollars)
    prev_year_amount = credit_amt_1978 * get_avg_wage_index(year - 3, config, economy=economy) / avg_wage_idx_1976
    prev_year_amount = int(round(prev_year_amount / 10.0) * 10.0)

    # Calculate current year's QC amount (rounded to nearest 10 dollars)
    curr_year_amount = credit_amt_1978 * get_avg_wage_index(year - 2, config, economy=economy) / avg_wage_idx_1976
    curr_year_amount = int(round(curr_year_amount / 10.0) * 10.0)

    # Pick the larger of the two
    return max(prev_year_amount, curr_year_amount)


def get_credits_for_year(
    year: int, earnings: float, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> int:
    """Compute the number of credits earned for a given year"""
    qc_earnings = get_qc_earnings_for_year(year, config, economy=economy)
    ss_config = _fin(config).social_security
    max_credits = ss_config.max_credits_per_year
    return min(max_credits, int(earnings / qc_earnings))


# Property accessors for configuration values
def get_min_eligible_credits(config: "FinancialConfig | None" = None) -> int:
    """Get minimum eligible credits from configuration"""
    return _fin(config).social_security.min_eligible_credits


def get_max_credits_per_year(config: "FinancialConfig | None" = None) -> int:
    """Get maximum credits per year from configuration"""
    return _fin(config).social_security.max_credits_per_year


def get_max_years_of_income(config: "FinancialConfig | None" = None) -> int:
    """Get maximum years of income from configuration"""
    return _fin(config).social_security.max_years_of_income


def get_min_early_retirement_age(config: "FinancialConfig | None" = None) -> int:
    """Get minimum early retirement age from configuration"""
    return _fin(config).social_security.min_early_retirement_age


def get_normal_retirement_age(config: "FinancialConfig | None" = None) -> int:
    """Get normal retirement age from configuration"""
    return _fin(config).social_security.normal_retirement_age


def get_delayed_retirement_credit(config: "FinancialConfig | None" = None) -> float:
    """Get delayed retirement credit from configuration"""
    return _fin(config).social_security.delayed_retirement_credit


def get_max_delayed_retirement_credit_age(config: "FinancialConfig | None" = None) -> int:
    """Get maximum delayed retirement credit age from configuration"""
    return _fin(config).social_security.max_delayed_retirement_credit_age


class Income:
    def __init__(self, year: int, amount: float):
        """Create an income record for a given year

        Args:
            year: The year of the income record
            amount: The amount of income for the given year
        """
        self.year = year
        self.amount = amount

    def _repr_html_(self):
        return f"<p>{self.year}: ${self.amount}</p>"

    def get_credits(self, config: "FinancialConfig | None" = None, economy: "EconomyModel | None" = None) -> int:
        """Compute the number of credits earned for a given year"""
        return get_credits_for_year(self.year, self.amount, config, economy=economy)

    def get_indexed_amount(
        self,
        person_age_60_year: int,
        config: "FinancialConfig | None" = None,
        economy: "EconomyModel | None" = None,
    ) -> float:
        """Compute the indexed amount for a given year

        Args:
            person_age_60_year: The year in which the person attains age 60
            config: Per-model config. Defaults to the packaged defaults.

        Returns:
            The indexed amount for the given year
        """
        if self.year >= person_age_60_year:
            return self.amount
        else:
            awi_at_60 = get_avg_wage_index(person_age_60_year, config, economy=economy)
            return self.amount * awi_at_60 / get_avg_wage_index(self.year, config, economy=economy)


def full_retirement_age(birth_year: int, config: "FinancialConfig | None" = None) -> float:
    """Full (normal) retirement age in years for a birth year (SSA's table: 65 through 1937, rising two
    months a year to 66 for 1943-54, then to 67 for 1960 and later)."""
    table = _fin(config).social_security.full_retirement_age_by_birth_year
    years, months = 65, 0
    for first_year, row_years, row_months in table:
        if birth_year >= first_year:
            years, months = row_years, row_months
    return years + months / 12


def spousal_reduction_factor(months_early: int) -> float:
    """The factor on a spousal benefit started ``months_early`` months before full retirement age:
    25/36 of 1% a month for the first 36 months, 5/12 of 1% beyond (42 U.S.C. 402(q)(1))."""
    months_early = max(0, months_early)
    reduction = min(months_early, 36) * (25 / 36) + max(0, months_early - 36) * (5 / 12)
    return 1 - reduction / 100


def earnings_test_exempt_amounts(
    year: int, config: "FinancialConfig | None" = None, *, economy: "EconomyModel | None" = None
) -> tuple[float, float]:
    """The retirement earnings test's annual ``(lower, higher)`` exempt amounts for ``year``: the
    published table, then the statutory formula (base monthly amount x AWI(year - 2) / AWI(base year),
    rounded to $10, never below the prior year's, x 12)."""
    cfg = _fin(config).social_security.earnings_test
    table = cfg.exempt_amounts
    if year in table:
        lower, higher = table[year]
        return float(lower), float(higher)
    last = max(table)
    if year < min(table):
        lower, higher = table[min(table)]
        return float(lower), float(higher)
    prior_lower, prior_higher = (amount / 12 for amount in table[last])
    for projected in range(last + 1, year + 1):
        awi = get_avg_wage_index(projected - 2, config, economy=economy)
        lower = cfg.lower_base_monthly * awi / get_avg_wage_index(cfg.lower_base_awi_year, config)
        higher = cfg.higher_base_monthly * awi / get_avg_wage_index(cfg.higher_base_awi_year, config)
        prior_lower = max(prior_lower, round(lower / 10) * 10)
        prior_higher = max(prior_higher, round(higher / 10) * 10)
    return prior_lower * 12, prior_higher * 12


class SocialSecurity(LifeModelAgent):
    """Social Security benefits: a monthly benefit from the month the person reaches
    ``withdrawal_start_age`` (exact age), at the year's primary insurance amount (with COLAs).

    Optional refinements: the PIA from the SSA statement (``pia_override``), full retirement age by birth
    year (``fra_from_birth_year``), the spousal benefit (``spousal_benefit``) and the retirement earnings
    test (``earnings_test``)."""

    # The earnings test reads the year's earnings before the income ledger is cleared (20).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 15}

    @deprecated_arguments(
        {"person": "owner", "withdrawal_start_age": "claim_age", "income_history": "earnings_history"}
    )
    def __init__(
        self,
        owner: Person,
        claim_age: float | None = None,
        earnings_history: list[Income] | list[tuple[int, float]] | None = None,
        *,
        pia_override_monthly: float | None = None,
        fra_from_birth_year: bool = False,
        spousal_benefit: bool = False,
        earnings_test: bool = False,
    ):
        """Models Social Security benefits for a person

        Args:
            owner: The person for whom to model Social Security benefits (``person=`` is deprecated)
            claim_age: The age at which the person starts claiming benefits (the
                ``withdrawal_start_age`` attribute; ``withdrawal_start_age=`` is deprecated)
            earnings_history: The person's covered earnings by year (``income_history=`` is deprecated)
            pia_override_monthly: The monthly benefit at full retirement age from the SSA statement, in today's
                (the model start's) dollars, instead of computing the PIA from ``income_history``
                (keyword-only). It is wage-indexed to the year the person turns 62 (the
                statement's "today's dollars" are wage-indexed), then gets the COLAs. The statement's
                estimate assumes work until full retirement age at the latest earnings; with an
                ``earnings_history`` too, the override is scaled by the ratio of the PIA recomputed from
                the earnings actually recorded (the history plus the simulated wages, zeros once retired)
                to the PIA of the statement's assumption (the history plus the latest year's earnings,
                wage-indexed, every year until full retirement age) -- SSA's own method of zero years.
                Without a history the override is used as is (it overstates an early retiree's benefit).
            fra_from_birth_year: Use the full retirement age of the person's birth year (66 and 6
                months for 1957, ...) instead of the configured ``normal_retirement_age``.
            spousal_benefit: Pay the spousal benefit: once both spouses have claimed, half the
                spouse's PIA less this person's own PIA (when positive), reduced for each month it
                starts before full retirement age (no delayed credits).
            earnings_test: Withhold benefits before full retirement age when earnings exceed the year's
                exempt amount ($1 for $2; $1 for $3 in the year of FRA, counting earnings before
                that month). The excess is withheld from the following months' checks, whole checks
                first; at full retirement age the reduction is recomputed without the withheld months.

        Raises:
            ValueError: If the withdrawal start age is before the earliest age for early withdrawal
        """
        person, withdrawal_start_age, income_history = owner, claim_age, earnings_history
        super().__init__(person.model)
        self.person = person
        self.withdrawal_start_age = withdrawal_start_age or person.retirement_age
        self.pia_override = pia_override_monthly
        self.fra_from_birth_year = fra_from_birth_year
        self.spousal_benefit = spousal_benefit
        self.earnings_test = earnings_test
        #: The year the PIA override's dollars are (the model's first year).
        self._override_year = self.model.start_year
        #: Benefits still to withhold under the earnings test, and the months fully withheld before FRA.
        self.withholding_due = 0.0
        self.months_withheld = 0
        self._earnings_by_month: dict[int, float] = {}
        self.stat_benefits_withheld = 0.0

        self.income_history = []
        if income_history is not None and len(income_history):
            for income in income_history:
                if isinstance(income, Income):
                    self.income_history.append(income)
                else:
                    self.income_history.append(Income(income[0], income[1]))
        #: The statement's earnings record when a PIA override comes with one: the override is then scaled
        #: for the years the run does not work before full retirement age (see ``pia_override_monthly``).
        self._statement_history: list[tuple[int, float]] | None = (
            [(income.year, income.amount) for income in self.income_history]
            if pia_override_monthly is not None and self.income_history
            else None
        )

        if self.withdrawal_start_age < get_min_early_retirement_age(self.model.config):
            raise ValueError("Withdrawal start age cannot be before early retirement age")

        # Monthly PIA floor granted as a Social Security survivor benefit when a spouse dies: the
        # survivor's benefit is raised to at least the deceased's benefit (approximation).
        self.survivor_pia_floor = 0.0
        # The year's PIA (it changes with COLAs only at year boundaries): {year: pia}.
        self._pia_by_year: dict[int, float] = {}

        # Register social security
        self.person.social_security = self

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Withdrawal Start Age: {self.withdrawal_start_age}</li>"
        desc += f"<li>Years of Work: {len(self.income_history)}</li>"
        desc += "</ul>"
        return desc

    def add_income_for_year(self, amount: float, year: int | None = None):
        """Add income to the person's income history

        Args:
            amount: The amount of income to add
            year: The year to add the income for. If not specified, the current year is used
        """
        year = year or self.model.year
        matching_years = [x for x in self.income_history if x.year == year]
        if matching_years:
            income_obj = matching_years[0]
            income_obj.amount += amount
        else:
            income_obj = Income(year, amount)
            self.income_history.append(income_obj)

        # Cap income at that year's Social Security wage base, read from the same per-year config FICA
        # uses, so the payroll-tax base and the AIME base are one source (including inflation-projected
        # future years).
        max_income = self.model.config_for_year(income_obj.year).tax.fica.social_security_max_income
        income_obj.amount = min(income_obj.amount, max_income)

    @property
    def withdrawal_start_year(self) -> int:
        """Returns the year in which the person starts withdrawing Social Security benefits"""
        return self.claim_period[0]

    @property
    def claim_period(self) -> tuple[int, int]:
        """``(year, month)`` of the first benefit: the month the person's exact age reaches
        ``withdrawal_start_age`` (January of that year for a whole-year age and a January birth)."""
        return self.person.get_period_at_age(self.withdrawal_start_age)

    @property
    def is_claiming(self) -> bool:
        """Whether benefits are being paid this month."""
        return (self.model.year, self.model.month) >= self.claim_period

    def get_indexed_income_history(self) -> list[float]:
        """Computes indexed earnings for a person"""
        age_60_year = self.person.get_year_at_age(60)
        return [x.get_indexed_amount(age_60_year, self.model.config, self.model.economy) for x in self.income_history]

    def get_aime(self, history: "list[Income] | None" = None) -> float:
        """Computes Average Indexed Monthly Earnings (AIME) for a person (from ``history``, default the
        earnings record)"""
        history = self.income_history if history is None else history

        # Make sure the person has enough credits to be eligible
        config = self.model.config
        credits_earned = sum(x.get_credits(config, self.model.economy) for x in history)
        if credits_earned < get_min_eligible_credits(config):
            return 0

        # Pick the highest 35 values from the list
        age_60_year = self.person.get_year_at_age(60)
        indexed_earnings = [x.get_indexed_amount(age_60_year, config, self.model.economy) for x in history]
        max_years = get_max_years_of_income(config)
        highest_earnings = sorted(indexed_earnings, reverse=True)[:max_years]

        return round(sum(highest_earnings) / (max_years * 12))

    def _formula_pia(self, aime: float, year_of_age_62: int) -> float:
        """The PIA formula (the bend points of the year the person turns 62) on ``aime``, truncated to the dime."""
        bend_points = get_bend_points(year_of_age_62, self.model.config, economy=self.model.economy)
        pia = min(aime, bend_points[0]) * 0.9
        pia += min(max(0, aime - bend_points[0]), bend_points[1] - bend_points[0]) * 0.32
        pia += max(0, aime - bend_points[1]) * 0.15
        return int(pia * 10) / 10.0

    def statement_assumed_history(self) -> list[Income]:
        """The earnings record an SSA statement's estimate assumes: the statement's history plus, for every
        year from the model's first year until the year before full retirement age, the latest year's
        earnings (wage-indexed, capped at each year's wage base). Empty without a statement history."""
        if not self._statement_history:
            return []
        config, economy = self.model.config, self.model.economy
        history = [Income(year, amount) for year, amount in self._statement_history]
        last_year, last_amount = max(
            ((year, amount) for year, amount in self._statement_history if amount > 0), default=(None, 0.0)
        )
        if last_year is None:
            return history
        fra_year = self._fra_period()[0]
        known = {year for year, _ in self._statement_history}
        for year in range(max(self.model.start_year, last_year + 1), fra_year):
            if year in known:
                continue
            amount = (
                last_amount
                * get_avg_wage_index(year, config, economy=economy)
                / get_avg_wage_index(last_year, config, economy=economy)
            )
            cap = self.model.config_for_year(year).tax.fica.social_security_max_income
            history.append(Income(year, min(amount, cap)))
        return history

    def override_scale(self) -> float:
        """The factor applied to the statement's PIA override for the years actually worked: the PIA from the
        recorded earnings over the PIA of the statement's assumed record (1.0 without a statement history)."""
        if not self._statement_history:
            return 1.0
        year_of_age_62 = self.person.get_year_at_age(62)
        assumed = self._formula_pia(self.get_aime(self.statement_assumed_history()), year_of_age_62)
        if assumed <= 0:
            return 1.0
        return self._formula_pia(self.get_aime(), year_of_age_62) / assumed

    @property
    def normal_retirement_age(self) -> float:
        """Full retirement age: the birth year's (``fra_from_birth_year``) or the configured one."""
        if self.fra_from_birth_year:
            return full_retirement_age(self.person.birth_year, self.model.config)
        return get_normal_retirement_age(self.model.config)

    def _fra_period(self) -> tuple[int, int]:
        """``(year, month)`` the person reaches full retirement age."""
        return self.person.get_period_at_age(self.normal_retirement_age)

    def get_early_delayed_pia(self, pia: float) -> float:
        """Computes the early or delayed PIA for a person

        Args:
            pia: The person's primary insurance amount

        Returns:
            PIA adjusted for early or delayed retirement
        """
        # Apply early/delayed retirement credits
        # https://www.ssa.gov/oact/quickcalc/early_late.html
        config = self.model.config
        normal_ret_age = self.normal_retirement_age
        if self.withdrawal_start_age < normal_ret_age:
            # Reduce for early withdrawal
            months_early = (normal_ret_age - self.withdrawal_start_age) * 12
            if self.months_withheld and (self.model.year, self.model.month) >= self._fra_period():
                # Adjustment of the reduction factor at FRA: months whose benefits the earnings test
                # withheld in full no longer count as early (42 U.S.C. 402(q)(7)).
                months_early = max(0.0, months_early - self.months_withheld)
            reduction_pct = min(months_early, 36) * 0.01 * (5 / 9)
            reduction_pct += max(0, months_early - 36) * 0.01 * (5 / 12)
            pia *= 1 - reduction_pct
        elif self.withdrawal_start_age > normal_ret_age:
            # Increase for delayed withdrawal
            max_del_age = get_max_delayed_retirement_credit_age(config)
            max_months_delayed = (max_del_age - normal_ret_age) * 12
            months_delayed = (self.withdrawal_start_age - normal_ret_age) * 12
            months_delayed = min(months_delayed, max_months_delayed)
            del_credit = get_delayed_retirement_credit(config)
            increase_pct = months_delayed * (del_credit / (100 * 12))
            pia *= 1 + increase_pct
        return pia

    def primary_insurance_amount(self, current_year: int | None = None) -> float:
        """The unreduced PIA (the benefit at full retirement age) in ``current_year``, with COLAs: from
        the earnings record's AIME and the bend points of the year the person turns 62, or the
        statement's ``pia_override``."""
        current_year = current_year or self.model.year
        year_of_age_62 = self.person.get_year_at_age(62)
        config, economy = self.model.config, self.model.economy
        if self.pia_override is not None:
            pia = float(self.pia_override)
            first_cola_year = self._override_year
            if self._override_year < year_of_age_62:
                # The statement's "today's dollars" are wage-indexed: grow them with the wage index to the
                # eligibility year, then COLAs.
                pia *= get_avg_wage_index(year_of_age_62 - 2, config, economy=economy) / get_avg_wage_index(
                    self._override_year - 2, config, economy=economy
                )
                pia = int(pia * 10) / 10.0
                first_cola_year = year_of_age_62
            if self._statement_history:
                # The estimate assumed work until full retirement age: scale it for the years not worked.
                pia = int(pia * self.override_scale() * 10) / 10.0
        else:
            # Round to the nearest lowest dime
            pia = self._formula_pia(self.get_aime(), year_of_age_62)
            first_cola_year = year_of_age_62
        for cola_year in range(first_cola_year, current_year):
            # This rounding seems to match the SSA's rounding (truncating to nearest lower dime)
            pia = int(pia * (1 + get_cost_of_living_adj(cola_year, config, economy=economy) / 100.0) * 10) / 10.0
        return pia

    def get_pia(self, current_year: int | None = None) -> float:
        """Computes Primary Insurance Amount (PIA) for a person
            Note: PIA is a monthly amount, so should be multiplied by 12 to get annual amount

        Args:
            current_year: The current year

        Returns:
            The person's PIA, adjusted for the claiming age (early reduction or delayed credits)
        """
        pia = self.primary_insurance_amount(current_year)
        # Apply early/delayed retirement credits
        pia = self.get_early_delayed_pia(pia)

        # Round to the nearest cent
        return round(pia, 2)

    def spousal_amount(self) -> float:
        """This month's spousal benefit (0 unless ``spousal_benefit`` and both spouses are claiming)."""
        spouse = self.person.spouse
        if not self.spousal_benefit or spouse is None or spouse.is_deceased:
            return 0.0
        worker = spouse.social_security
        if worker is None or not worker.is_claiming or not self.is_claiming:
            return 0.0
        year = self.model.year
        percent = self.model.config.social_security.spousal_benefit_percent
        excess = percent / 100 * worker.primary_insurance_amount(year) - self.primary_insurance_amount(year)
        if excess <= 0:
            return 0.0
        start = max(self.claim_period, worker.claim_period)
        fra = self._fra_period()
        months_early = max(0, (fra[0] * 12 + fra[1]) - (start[0] * 12 + start[1]))
        return round(excess * spousal_reduction_factor(months_early), 2)

    def monthly_benefit(self) -> float:
        """This month's benefit: the year's PIA (computed once a year), floored at any survivor
        benefit, plus any spousal benefit."""
        year = self.model.year
        pia = self._pia_by_year.get(year)
        if pia is None:
            pia = self._pia_by_year[year] = self.get_pia()
        return max(pia, self.survivor_pia_floor) + self.spousal_amount()

    def pre_step(self):
        # Pay the month's benefit once benefits have started: the gross benefit is deposited as cash
        # and recorded on the income ledger. How much of the year's benefits is taxable depends on
        # the whole return's provisional income (spouse's income, gains, RSU vests, the year-end
        # withdrawal), so the tax unit computes the taxable portion at settlement
        # (TaxUnit.taxable_social_security); nothing here depends on which other income has
        # already been booked.
        if self.person.is_deceased:
            # Benefits stop at death (a surviving spouse's survivor floor is applied to their own
            # record in Person._apply_survivor_adjustments).
            return
        if self.is_claiming:
            if self.months_withheld and (self.model.year, self.model.month) == self._fra_period():
                self._pia_by_year.pop(self.model.year, None)  # the reduction is recomputed at FRA
            benefit = self.monthly_benefit()
            if self.withholding_due > 0:
                withheld = min(benefit, self.withholding_due)
                self.withholding_due -= withheld
                self.stat_benefits_withheld = snap_money(self.stat_benefits_withheld + withheld)
                if withheld >= benefit and (self.model.year, self.model.month) < self._fra_period():
                    self.months_withheld += 1
                benefit -= withheld
            if benefit <= 0:
                return
            self.person.income.add_social_security(benefit)
            self.person.receive_cash(benefit, source="Social Security", kind=FlowKind.BENEFIT)
            self.person.stat_ss_income = snap_money(self.person.stat_ss_income + benefit)

    def step(self):
        """Record the year's earnings so far (wages and self-employment) for the earnings test."""
        if self.earnings_test:
            ledger = self.person.income
            self._earnings_by_month[self.model.month] = ledger.fica_wages + ledger.self_employment_income

    def on_year_start(self):
        self._earnings_by_month = {}

    def earnings_test_withholding(self) -> float:
        """The benefits this year's earnings require withholding (0 at or after full retirement age, and
        in years without benefits)."""
        if not self.earnings_test or not self._earnings_by_month or self.person.is_deceased:
            return 0.0
        year = self.model.year
        fra_year, fra_month = self._fra_period()
        claim_year, claim_month = self.claim_period
        if year > fra_year or year < claim_year:
            return 0.0
        lower, higher = earnings_test_exempt_amounts(year, self.model.config, economy=self.model.economy)
        cfg = self.model.config.social_security.earnings_test
        months = sorted(self._earnings_by_month)
        if year == fra_year:
            before = [m for m in months if m < fra_month]
            earnings = self._earnings_by_month[before[-1]] if before else 0.0
            excess, ratio = earnings - higher, cfg.higher_withholding_ratio
        else:
            earnings = self._earnings_by_month[months[-1]]
            excess, ratio = earnings - lower, cfg.lower_withholding_ratio
        if excess <= 0:
            return 0.0
        # No more than the benefits of the year's months before FRA (from the claim month).
        first = claim_month if year == claim_year else 1
        last = fra_month - 1 if year == fra_year else 12
        months_due = max(0, last - first + 1)
        cap = months_due * self.monthly_benefit()
        return min(excess / ratio, cap)

    def on_year_end(self):
        withholding = self.earnings_test_withholding()
        if withholding > 0:
            self.withholding_due += withholding
            self.model.event_log.add(
                Event(
                    f"{self.person.name}'s {self.model.year} earnings exceed the Social Security earnings test: "
                    f"${withholding:,.0f} of benefits withheld from the next checks"
                )
            )

    def _taxable_benefit_portion(self, annual_benefit: float) -> float:
        """Taxable portion of ``annual_benefit`` on this person's own ledger (IRS Pub. 915).

        A single-person view for inspection: provisional income is this person's own non-Social
        Security income (ordinary + preferential + tax-exempt interest) plus half the benefit, at
        the person's filing status. The engine taxes benefits at settlement from the whole tax
        unit's income instead (see :meth:`TaxUnit.taxable_social_security`).
        """
        ledger = self.person.income
        other_income = (
            ledger.ordinary_taxable
            - ledger.taxable_social_security
            + ledger.preferential_income
            + ledger.tax_exempt_interest
        )
        return taxable_social_security(annual_benefit, other_income, self.person.filing_status, self.model.config)

    @property
    def html_report(self) -> str:
        """Returns a detailed report of the person's social security benefits"""
        desc = "<ul>"
        desc += f"<li>Withdrawal Start Age: {self.withdrawal_start_age}</li>"
        desc += f"<li>Years of Work: {len(self.income_history)}</li>"
        desc += "<li><ul>"
        desc += "".join(f"<li>{x._repr_html_()}</li>" for x in self.income_history)
        desc += "</ul></li>"
        desc += f"<li>AIME: {self.get_aime()}</li>"
        desc += f"<li>PIA: {self.get_pia()}</li>"
        desc += "</ul>"
        return desc
