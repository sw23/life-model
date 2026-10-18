# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import html
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from ..ledger import FlowKind
from ..limits import job_401k_annual_additions_limit
from ..model import Event, EventKind, LifeModel, LifeModelAgent, snap_money
from ..people.person import Person

if TYPE_CHECKING:
    from ..account.job401k import Job401kAccount
    from ..account.traditional_IRA import TraditionalIRA
    from .payroll import PayrollDeductions
    from .stock import StockPlan

#: Ledger cause of a self-employed person's own employer (SEP / profit-sharing) contribution.
SELF_EMPLOYED_EMPLOYER_CAUSE = "self-employed plan contribution (employer)"


@dataclass(frozen=True)
class Payroll:
    """A paycheck (or a sum of paychecks) for a job: gross pay and its 401k split (all dollars)."""

    gross: float = 0.0
    pretax: float = 0.0
    roth: float = 0.0
    match: float = 0.0
    #: The bonus part of ``gross``.
    bonus: float = 0.0
    #: Dependent care FSA (W-2 jobs; excluded from wages).
    fsa: float = 0.0

    @property
    def elective(self) -> float:
        """Employee elective deferrals (pre-tax + Roth)."""
        return self.pretax + self.roth

    def is_close(self, other: "Payroll", tolerance: float = 1e-6) -> bool:
        """Whether every component matches ``other`` within ``tolerance`` dollars."""
        return all(
            abs(a - b) <= tolerance
            for a, b in (
                (self.gross, other.gross),
                (self.pretax, other.pretax),
                (self.roth, other.roth),
                (self.match, other.match),
                (self.fsa, other.fsa),
            )
        )

    def __add__(self, other: "Payroll") -> "Payroll":
        return Payroll(
            gross=self.gross + other.gross,
            pretax=self.pretax + other.pretax,
            roth=self.roth + other.roth,
            match=self.match + other.match,
            bonus=self.bonus + other.bonus,
            fsa=self.fsa + other.fsa,
        )

    def __sub__(self, other: "Payroll") -> "Payroll":
        return Payroll(
            gross=self.gross - other.gross,
            pretax=self.pretax - other.pretax,
            roth=self.roth - other.roth,
            match=self.match - other.match,
            bonus=self.bonus - other.bonus,
            fsa=self.fsa - other.fsa,
        )


class Job(LifeModelAgent):
    """A W-2 job, paid monthly.

    Each month the job pays a twelfth of the base salary (plus the bonus in the salary's
    ``bonus_month``), defers into its 401k per paycheck with the 402(g) room checked against
    everything deferred so far this year (so a high deferral rate stops when the limit is reached,
    as it really does), and posts the employer match per paycheck (capped by the year's 415(c)
    room). With ``Job401kAccount(match_true_up=True)`` (the default) the December paycheck tops the
    match up to the plan formula on the year's totals. Wages, deferrals and FICA wages land on the
    owner's income ledger as they are paid; the year's taxes are settled in December.
    """

    STATS_OWNED = frozenset({"stat_gross_income", "stat_retirement_contrib", "stat_retirement_match"})

    # Payroll true-up runs early in the step stage: after the events stage (so this month's job and
    # salary changes are seen), before account growth (-10) and the month's bills (0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"step": -30}

    #: Job kinds: a W-2 employee, or a sole proprietorship (Schedule C).
    KINDS = ("w2", "self_employed")

    def __init__(
        self,
        owner: Person,
        company: str,
        role: str,
        salary: "Salary",
        *,
        kind: str = "w2",
        expenses_annual: float = 0.0,
        payroll: "PayrollDeductions | None" = None,
        sep_account: "TraditionalIRA | None" = None,
        plan_contribution_percent: float = 0.0,
        sstb: bool = False,
    ):
        """Job

        Args:
            owner (Person): Person who owns the job.
            company (str): Company name (the business, for a self-employed job).
            role (str): Job title.
            salary (Salary): Salary of the job. For ``kind="self_employed"`` it is the business's gross
                receipts (raises and the bonus percentage grow and add to them).
            kind: ``"w2"`` (default) or ``"self_employed"``: a sole proprietorship whose net profit
                (receipts less ``expenses_annual``) is paid to the bank a twelfth a month like wages but is Schedule C
                income: no FICA withholding, self-employment tax on Schedule SE (sharing the Social
                Security wage base with the person's W-2 wages), half of it an adjustment, and the
                qualified business income deduction. No withholding or estimated payments until Plan 31
                task 6: the tax is settled with the year.
            expenses_annual: Business expenses (self-employed only), in start-year dollars; they scale
                with the receipts so the margin is constant.
            payroll: Pre-tax payroll deductions (W-2 jobs; :class:`~life_model.work.payroll.PayrollDeductions`).
            sep_account: A traditional IRA receiving the self-employed person's SEP contribution.
            plan_contribution_percent: The SEP (or solo 401(k) profit-sharing) plan rate, at most 25%; the
                owner's own contribution is figured with Pub. 560's self-employed rate (rate / (1 + rate))
                on net profit less half of SE tax, within the §401(a)(17) and §415(c) limits. A solo 401(k)
                is a ``Job401kAccount`` on this job: its deferral percentages apply to the same net earnings.
                The contributions are made with December's payment, on the year's profit.
            sstb: The business is a specified service trade or business (§199A(d)(2)).
        """
        if kind not in self.KINDS:
            raise ValueError(f"Unknown job kind {kind!r}; expected one of {self.KINDS}")
        if kind == "w2" and (expenses_annual or sep_account is not None or plan_contribution_percent):
            raise ValueError("expenses_annual, sep_account and plan_contribution_percent are for self-employed jobs")
        if kind == "self_employed" and payroll is not None:
            raise ValueError("payroll deductions are for W-2 jobs")
        super().__init__(owner.model)
        self.owner = owner
        self.company = company
        self.role = role
        self.salary = salary
        if getattr(salary, "owner", None) is None:
            salary.owner = owner  # whose salary it is (reporting: the agent frame's Owner column)
        self.kind = kind
        self.expenses_annual = expenses_annual
        self._receipts_at_start = salary.base
        self.payroll = payroll
        self.sep_account = sep_account
        self.plan_contribution_percent = plan_contribution_percent
        self.sstb = sstb
        self.retirement_account: Job401kAccount | None = None
        # Set by StockPlan when one attaches to this job. Vest income is deliberately excluded from
        # the 401(k)-eligible compensation computed below, matching the usual plan-document rule.
        self.stock_plan: StockPlan | None = None
        self.retired = False
        # Years of service: a year counts once its first paycheck is booked (a paid year is a worked
        # year, including a part year). Drives 401k match vesting and pension service credit.
        self.years_of_service = 0
        # What this job has booked for the month ``_booked_period`` (see ``_book_payroll``).
        self._booked: Payroll | None = None
        self._booked_period: int | None = None
        #: The last year this job booked a paycheck in (pension service credit reads it).
        self._booked_year: int | None = None
        # The year's payroll so far (all booked months), and the plan pay behind its 401k split.
        self._ytd = Payroll()
        self._ytd_compensation = 0.0
        self._ytd_year: int | None = None
        self._booked_month_compensation = 0.0

        self.stat_gross_income = 0
        self.stat_retirement_contrib = 0
        self.stat_retirement_match = 0

        # Register with the model registry
        self.model.registries.jobs.register(self.owner, self)

    def _repr_html_(self):
        return f"{html.escape(self.role)} at {html.escape(self.company)}"

    def _start_year_to_date(self) -> None:
        if self._ytd_year != self.model.year:
            self._ytd = Payroll()
            self._ytd_compensation = 0.0
            self._ytd_year = self.model.year

    def _booked_this_month(self) -> "Payroll | None":
        return self._booked if self._booked_period == self.model.period else None

    def _compute_payroll(self) -> "Payroll":
        """This month's paycheck at the current salary and 401k elections (pure; moves no money).

        The 402(g) room is the person's remaining room for the year plus whatever this job already
        booked this month, so recomputing after a mid-month change (see :meth:`step`) doesn't count
        the job's own earlier deferral against it.
        """
        if self.kind == "self_employed":
            return self._compute_self_employed_payroll()
        self._start_year_to_date()
        booked = self._booked_this_month() or Payroll()
        base = self.salary.base / 12
        bonus = self.salary.bonus if self.model.month == self.salary.bonus_month else 0.0
        gross_income = base + bonus
        pretax = roth = match = 0.0
        fsa = 0.0
        if self.payroll is not None:
            # A twelfth of the year's election from each paycheck (W-2 box 10).
            fsa = min(self.payroll.dependent_care_fsa_annual / 12, gross_income)
        if self.retirement_account is not None:
            account = self.retirement_account
            # Plan pay: base salary, plus the bonus when the plan counts it (match_on_bonus).
            compensation = account.plan_compensation(base, bonus)
            # Elective deferrals share one 402(g) limit across all of the person's jobs, so two
            # jobs can no longer each defer the full limit.
            room = min(self.owner.remaining_401k_elective_room() + booked.elective, compensation)
            pretax = min(account.pretax_contrib(compensation), room)
            room -= pretax
            roth = min(account.roth_contrib(compensation), room)
            elective = pretax + roth

            # Employer match from the plan formula (match tiers, or the deprecated legacy percent) on
            # this paycheck, or in December (true-up plans) on the year's totals less what was
            # already matched; capped by the year's 415(c) overall annual-additions limit (employee
            # + employer money per plan) so the match can't run away.
            prior = self._ytd - booked
            additions_limit = job_401k_annual_additions_limit(self.owner.model.year_config)
            year_elective = prior.elective + elective
            if account.match_true_up and self.model.month == 12:
                # December true-up: the year's match is the formula on the year's totals, capped by
                # 415(c); this paycheck pays the difference (negative when the paychecks overshot).
                year_compensation = self._ytd_compensation - self._booked_compensation() + compensation
                year_match = account.employer_match(year_elective, year_compensation)
                match = max(0.0, min(year_match, additions_limit - year_elective)) - prior.match
            else:
                match = account.employer_match(elective, compensation)
                match = max(0.0, min(match, additions_limit - year_elective - prior.match))
        return Payroll(gross=gross_income, pretax=pretax, roth=roth, match=match, bonus=bonus, fsa=fsa)

    def _booked_compensation(self) -> float:
        """Plan pay of the paycheck already booked this month (0 when none is)."""
        return self._booked_month_compensation if self._booked_this_month() is not None else 0.0

    def net_profit(self) -> float:
        """This year's Schedule C net profit of a self-employed job at the current receipts: receipts
        (base plus bonus) less expenses (which scale with the receipts)."""
        receipts = self.salary.base + self.salary.bonus
        return receipts - self._expenses_now()

    def _expenses_now(self) -> float:
        scale = self.salary.base / self._receipts_at_start if self._receipts_at_start > 0 else 1.0
        return self.expenses_annual * scale

    def _month_profit(self) -> float:
        """This month's net profit: a twelfth of the receipts less a twelfth of the expenses, plus the bonus
        (extra receipts) in the salary's ``bonus_month``."""
        bonus = self.salary.bonus if self.model.month == self.salary.bonus_month else 0.0
        return (self.salary.base - self._expenses_now()) / 12 + bonus

    def _year_w2_social_security_wages(self) -> float:
        """The person's W-2 Social Security wages for the year from their other jobs (what they paid so far
        plus this month's paycheck if not booked yet), for the wage base Schedule SE shares."""
        total = 0.0
        for job in self.owner.jobs:
            if job is self or job.kind != "w2":
                continue
            ytd = job._ytd if job._ytd_year == self.model.year else Payroll()
            if not job.retired and job._booked_this_month() is None:
                ytd = ytd + job._compute_payroll()
            total += ytd.gross - ytd.fsa
        return total

    def _compute_self_employed_payroll(self) -> "Payroll":
        """A self-employed month: the month's net profit as ``gross`` (paid to the bank like wages, no
        withholding). The owner's own plan contributions are made with the December payment, figured on the
        year's profit (Pub. 560: SEP / profit-sharing contributions are figured on the year's net earnings
        and may be deposited up to the filing deadline; solo 401(k) deferrals are elected by year end):
        ``match`` is the employer (SEP / profit-sharing) part, ``pretax`` / ``roth`` the solo 401(k)
        deferrals. Half of SE tax uses the year's W-2 Social Security wages (Pub. 560 worksheet steps 1-3).
        The contribution is limited to the cash on hand (bank plus the December profit)."""
        from ..tax.self_employment import self_employed_plan_contribution, self_employment_tax

        self._start_year_to_date()
        booked = self._booked_this_month() or Payroll()
        profit = self._month_profit()
        account = self.retirement_account
        if self.model.month != 12 or (account is None and self.sep_account is None):
            return Payroll(gross=profit)
        config = self.owner.model.year_config
        year_profit = (self._ytd - booked).gross + profit
        base = config.tax.fica.social_security_max_income
        se = self_employment_tax(year_profit, min(self._year_w2_social_security_wages(), base), config)
        if year_profit <= 0:
            return Payroll(gross=profit)
        compensation = max(0.0, year_profit - se.deduction)
        plan = self_employed_plan_contribution(
            year_profit,
            se.deduction,
            self.plan_contribution_percent,
            config,
            elective_pretax_wanted=account.pretax_contrib(compensation) if account is not None else 0.0,
            elective_roth_wanted=account.roth_contrib(compensation) if account is not None else 0.0,
            elective_room=self.owner.remaining_401k_elective_room() + booked.elective if account is not None else 0.0,
        )
        pretax, roth, employer = plan.elective_pretax, plan.elective_roth, plan.employer
        cash = self.owner.bank_account_balance + booked.elective + booked.match + profit - booked.gross
        total = pretax + roth + employer
        if total > cash > 0:
            scale = cash / total
            pretax, roth, employer = pretax * scale, roth * scale, employer * scale
        elif cash <= 0:
            pretax = roth = employer = 0.0
        return Payroll(gross=profit, pretax=pretax, roth=roth, match=employer)

    def _apply_self_employed(self, delta: "Payroll") -> None:
        """Move ``delta`` of a self-employed month: the net profit to the bank as business income, the
        owner's plan contributions (December) on to the SEP IRA / solo 401(k), Schedule C income and the
        plan deduction to the income ledger, and the net earnings to the Social Security record."""
        from ..tax.income import IncomeType

        owner = self.owner
        ledger = self.model.ledger
        pay_to = owner.cash_destination
        true_up = self._booked_this_month() is not None
        when = f"{self.model.year}-{self.model.month:02d}"
        cause = f"{when} business profit true-up" if true_up else f"{when} business profit"
        ledger.post(
            delta.gross, FlowKind.BUSINESS_INCOME, to_account=pay_to, source=self.company, cause=cause, agent=owner
        )
        contributed = delta.elective + delta.match
        account = self.retirement_account
        if account is not None:
            owner.record_401k_elective_deferral(delta.elective)
            account.pretax_balance = snap_money(account.pretax_balance + delta.pretax + delta.match)
            account.roth_balance = snap_money(account.roth_balance + delta.roth)
            ledger.post(
                delta.pretax,
                FlowKind.CONTRIBUTION,
                from_account=pay_to,
                to_account=account,
                cause="solo 401k pre-tax deferral",
                agent=owner,
            )
            ledger.post(
                delta.roth,
                FlowKind.CONTRIBUTION,
                from_account=pay_to,
                to_account=account,
                cause="solo 401k Roth deferral",
                agent=owner,
            )
            target = account
        else:
            target = self.sep_account
            if target is not None:
                target.balance = snap_money(target.balance + delta.match)
        if target is not None:
            ledger.post(
                delta.match,
                FlowKind.CONTRIBUTION,
                from_account=pay_to,
                to_account=target,
                cause=SELF_EMPLOYED_EMPLOYER_CAUSE,
                agent=owner,
            )
        take_home = delta.gross - contributed
        if take_home >= 0:
            owner.deposit_into_bank_account(take_home, post=False)
        else:
            owner.add_debt(owner.deduct_from_bank_accounts(-take_home), to_account=pay_to, cause=cause)
        owner.income.add(IncomeType.SELF_EMPLOYMENT, delta.gross, source="schedule_c")
        deductible = delta.match + delta.pretax
        if deductible:
            owner.income.add(IncomeType.ORDINARY, -deductible, source="self_employed_plan")
        if owner.social_security is not None:
            se = self.model.year_config.tax.self_employment
            owner.social_security.add_income_for_year(max(0.0, delta.gross) * se.net_earnings_percent / 100)
        self._ytd = self._ytd + delta
        self.stat_gross_income = snap_money(self.stat_gross_income + delta.gross)
        self.stat_retirement_contrib = snap_money(self.stat_retirement_contrib + delta.elective)
        self.stat_retirement_match = snap_money(self.stat_retirement_match + delta.match)

    def _apply_payroll(self, delta: "Payroll") -> None:
        """Move ``delta`` of payroll: take-home pay to the bank, deferrals and match to the 401k,
        wages to the income ledger and the Social Security earnings record.

        ``delta`` is a whole paycheck the first time, or the difference between a re-computed and
        the already-booked paycheck after a mid-month change (components may be negative).
        """
        if self.kind == "self_employed":
            self._apply_self_employed(delta)
            return
        owner = self.owner
        ledger = self.model.ledger
        pay_to = owner.cash_destination
        true_up = self._booked_this_month() is not None
        when = f"{self.model.year}-{self.model.month:02d}"
        cause = f"{when} payroll true-up" if true_up else f"{when} payroll"
        # Gross pay arrives in the bank; the deferrals move on to the 401k (amounts are negative
        # when a mid-month change claws pay back).
        ledger.post(
            delta.gross - delta.bonus, FlowKind.WAGE, to_account=pay_to, source=self.company, cause=cause, agent=owner
        )
        ledger.post(delta.bonus, FlowKind.BONUS, to_account=pay_to, source=self.company, cause=cause, agent=owner)
        if self.retirement_account is not None:
            account = self.retirement_account
            owner.record_401k_elective_deferral(delta.elective)
            account.pretax_balance = snap_money(account.pretax_balance + delta.pretax)
            account.receive_match(delta.match)
            account.pretax_balance = snap_money(account.pretax_balance)
            account.roth_balance = snap_money(account.roth_balance + delta.roth)
            ledger.post(
                delta.pretax,
                FlowKind.CONTRIBUTION,
                from_account=pay_to,
                to_account=account,
                cause="pre-tax 401k deferral",
                agent=owner,
            )
            ledger.post(
                delta.roth,
                FlowKind.CONTRIBUTION,
                from_account=pay_to,
                to_account=account,
                cause="Roth 401k deferral",
                agent=owner,
            )
            ledger.post(
                delta.match,
                FlowKind.MATCH,
                to_account=account,
                source=self.company,
                cause="employer match",
                agent=owner,
            )

        take_home = delta.gross - delta.elective
        if take_home >= 0:
            # Deposit take-home pay into bank account
            owner.deposit_into_bank_account(take_home, post=False)
        else:
            # A mid-month pay cut claws back pay that was already deposited; whatever the bank
            # can't return is owed (the unit settles it with the month's bills).
            owner.add_debt(owner.deduct_from_bank_accounts(-take_home), to_account=pay_to, cause=cause)

        # Add to taxable income for the person
        # - Income tax is settled by the tax unit at year end
        # - Elective pre-tax 401k deferrals reduce ordinary income but are still FICA wages, so
        #   the full gross is recorded as the FICA base (fixes the understated-FICA bug).
        # A dependent-care FSA election is excluded from wages for income tax and FICA (W-2 box 10). The
        # cash is unchanged: the FSA pays the care bill the household's spending already carries.
        self.owner.income.add_wages(
            ordinary_amount=delta.gross - delta.pretax - delta.fsa, fica_wages=delta.gross - delta.fsa
        )
        self.owner.income.dependent_care_benefits += delta.fsa
        if self.owner.social_security is not None:
            self.owner.social_security.add_income_for_year(delta.gross - delta.fsa)
        self._ytd = self._ytd + delta
        self.stat_gross_income = snap_money(self.stat_gross_income + delta.gross)
        self.stat_retirement_contrib = snap_money(self.stat_retirement_contrib + delta.elective)
        self.stat_retirement_match = snap_money(self.stat_retirement_match + delta.match)

    def _book_payroll(self) -> None:
        """Book this month's paycheck, or true it up against what was already booked this month."""
        payroll = self._compute_payroll()
        account = self.retirement_account
        compensation = (
            account.plan_compensation(self.salary.base / 12, payroll.bonus) if account is not None else payroll.gross
        )
        booked = self._booked_this_month()
        if booked is None:
            if self._booked_year != self.model.year:
                self.years_of_service += 1
            self._apply_payroll(payroll)
            self._ytd_compensation += compensation
        elif not payroll.is_close(booked):
            self._apply_payroll(payroll - booked)
            self._ytd_compensation += compensation - self._booked_compensation()
        else:
            payroll = booked
        self._booked = payroll
        self._booked_month_compensation = compensation
        self._booked_period = self.model.period
        self._booked_year = self.model.year
        if self.retirement_account is not None:
            self.retirement_account.vest_match()

    # Wages are booked in pre_step so taxable income and cash are in place before the events and
    # step stages (premiums, donations and the month's bills read them).
    def pre_step(self):
        if self.retired:
            return
        self._book_payroll()

    def step(self):
        """Payroll true-up (priority -30: after the events stage, before growth and the month's bills).

        A job started by a life event this month (built after ``pre_step`` ran) books its first
        paycheck here, and a salary or 401k-election change made by a life event this month is trued
        up against what ``pre_step`` booked, so both apply from this month. A job that retires
        mid-month keeps the month's booked pay (it stops from the next month).
        """
        if self.retired:
            return
        self._book_payroll()

    def retire(self):
        """Retire from the job (unvested employer 401k money is forfeited)."""
        if self.retired:
            return
        self.retired = True
        if self.retirement_account is not None:
            self.retirement_account.forfeit_unvested_match()
        self.model.event_log.add(
            Event(
                EventKind.RETIRED,
                person=self.owner,
                cause=self.company,
                message=f"{self.owner.name} retired from {self.company}",
            )
        )


class Salary(LifeModelAgent):
    # The raise runs at year end after the year's taxes are settled (0).
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 10}

    def __init__(
        self,
        model: LifeModel,
        base: float,
        yearly_increase: float | None = 0,
        yearly_bonus: float = 0,
        *,
        bonus_month: int | None = None,
    ):
        """Salary

        Args:
            base (float): Base salary (a year's pay; the job pays a twelfth each month).
            yearly_increase (float, optional): Yearly percentage increase. Pass None to grow with the
                economy's wage growth each year. Defaults to 0 (no increase).
            yearly_bonus (float): Yearly percentage bonus.
            bonus_month (int, optional): Month (1-12) the bonus is paid in (keyword-only). Defaults to
                the configured ``payroll.bonus_month`` (March).
        """
        super().__init__(model)
        self.base = base
        self._yearly_increase_override = yearly_increase
        self.yearly_bonus = yearly_bonus
        if bonus_month is None:
            bonus_month = model.config.payroll.bonus_month
        if not 1 <= int(bonus_month) <= 12:
            raise ValueError(f"bonus_month must be 1-12, got {bonus_month}")
        self.bonus_month = int(bonus_month)
        #: The person paid this salary (set by ``Job``).
        self.owner = None

    @property
    def yearly_increase(self) -> float:
        """Yearly percentage increase: the explicit override if set, else the economy's wage growth."""
        if self._yearly_increase_override is not None:
            return self._yearly_increase_override
        return self.model.economy.wage_growth(self.model.year)

    @yearly_increase.setter
    def yearly_increase(self, value: float | None) -> None:
        self._yearly_increase_override = value

    @property
    def bonus(self) -> float:
        """The year's bonus (paid in ``bonus_month``)."""
        return self.base * (self.yearly_bonus / 100)

    @property
    def base_salary(self) -> float:
        """The base salary (an alias of ``base`` reported as the agent frame's ``Salary`` column,
        snapshotted before the year-end raise)."""
        return self.base

    def on_year_end(self):
        # Escalator runs after the year's income has been earned/deposited (consume-then-advance).
        # A salary set up by a life event this year was already paid this year (Job.step books it),
        # so it escalates at this year end like any other: no creation-year special case.
        self.base += self.base * (self.yearly_increase / 100)
