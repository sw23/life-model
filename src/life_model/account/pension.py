# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE
import html
from typing import TYPE_CHECKING, ClassVar

from ..base_classes import Benefit
from ..deprecated_names import deprecated_arguments
from ..ledger import FlowKind
from ..model import snap_money
from ..people.person import Person
from ..tax.income import IncomeType

if TYPE_CHECKING:
    from ..work.job import Job


class Pension(Benefit):
    """Models a defined-benefit pension plan that pays a person a flat annual benefit in retirement.

    The benefit is wired into the simulation like the :class:`~life_model.insurance.social_security.SocialSecurity`
    agent: once the person is eligible, each month's ``pre_step`` deposits a twelfth of the annual
    benefit as cash and records it in the income ledger as
    :class:`~life_model.tax.income.IncomeType.PENSION` — ordinary taxable income with **no FICA**
    (retirees pay no payroll tax on pension income). A cost-of-living adjustment compounds the
    benefit at each year end.

    The annual benefit is either given directly (``benefit_amount``) or accrued from the standard
    defined-benefit formula ``years_of_service x benefit_multiplier% x final_salary``. Benefits are
    paid only once the participant is vested (``years_of_service >= vesting_years``).

    Service accrues while the participant works for the sponsor: every year the sponsoring job
    (``job``, or else the person's job whose ``company`` equals the pension's) books payroll adds a
    year of service, so an unvested participant vests by working, and a formula benefit grows with
    service, its ``final_salary`` following that job's base salary.

    Simplifications:
      * Without ``salary_history`` and ``final_average_years`` the formula uses the latest base salary
        as "final salary" (no final-average window).
      * Survivor benefits are a flat ``survivor_percent`` of the benefit continued to a surviving
        spouse at the retiree's death (see :meth:`Person.die`); the retiree's own benefit is reduced
        for the election only as ``survivor_reduction`` says.
    """

    STATS_OWNED = frozenset({"stat_pension_income"})
    # Service accrues at year end before the salary escalator (10) so "final salary" is this year's;
    # the COLA follows it.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"on_year_end": 5}

    @deprecated_arguments(
        {
            "person": "owner",
            "benefit_amount": "benefit_annual",
            "cola_percent": "cola_pct",
            "survivor_percent": "survivor_pct",
            "benefit_multiplier": "benefit_multiplier_pct",
            "final_salary": "final_salary_annual",
        },
        positional=("company", "vesting_years", "benefit_annual"),
    )
    def __init__(
        self,
        owner: Person,
        *,
        company: str,
        vesting_years: int,
        benefit_annual: float = 0.0,
        start_age: float | None = None,
        cola_pct: float = 0.0,
        survivor_pct: float = 0.0,
        years_of_service: int | None = None,
        benefit_multiplier_pct: float | None = None,
        final_salary_annual: float | None = None,
        job: "Job | None" = None,
        salary_history: "dict[int, float] | None" = None,
        final_average_years: int | None = None,
        normal_retirement_age: float | None = None,
        early_reduction_pct_per_year: float = 0.0,
        survivor_reduction: "float | str | None" = None,
        employee_basis: float = 0.0,
        lump_sum: bool = False,
        lump_sum_amount: float | None = None,
        lump_sum_rate_pct: float | None = None,
        rollover_account=None,
    ):
        """Models a pension plan for a person

        Every argument after the owner is keyword-only. Deprecated (one release): positional arguments,
        and the names ``person`` (owner), ``benefit_amount`` (benefit_annual), ``cola_percent``
        (cola_pct), ``survivor_percent`` (survivor_pct), ``benefit_multiplier`` (benefit_multiplier_pct)
        and ``final_salary`` (final_salary_annual).

        Args:
            owner: The person to which this pension belongs
            company: The company providing the pension
            vesting_years: Number of years required for vesting
            benefit_annual: Flat annual benefit amount (ignored when the accrual formula is given)
            start_age: Age at which benefits begin. Defaults to None, meaning benefits start at the
                person's retirement age.
            cola_pct: Annual cost-of-living adjustment applied to the benefit once in pay
                (e.g. 2.0 for +2% per year). Defaults to 0.0 (level benefit).
            survivor_pct: Percentage of the benefit continued to a surviving spouse when the
                retiree dies (e.g. 50.0 for a 50% joint-and-survivor election). Defaults to 0.0
                (single-life: the benefit terminates at death).
            years_of_service: Years of credited service. Defaults to ``vesting_years`` (vested).
            benefit_multiplier_pct: Percent of final salary accrued per year of service (e.g. 1.5).
            final_salary_annual: Final (or final-average) salary used by the accrual formula.
            job: The sponsoring job whose service accrues to this pension. Defaults to None, which
                uses the person's job at ``company`` (if any) each year.
            salary_history: Covered pay by year from the plan statement ``{year: salary}``
                (keyword-only). With ``final_average_years`` the formula's final salary is the
                highest average of that many consecutive years (the sponsoring job's pay is added as
                service accrues); without it, the latest year.
            final_average_years: Length of the final-average-pay window (3 or 5 are common).
            normal_retirement_age: The plan's normal retirement age, for the early-retirement reduction.
            early_reduction_pct_per_year: Reduction of the benefit per year it starts before the normal
                retirement age (prorated by month), e.g. 6.
            survivor_reduction: How a survivor election (``survivor_percent``) reduces the retiree's
                own benefit: a percent (the plan's joint-and-survivor factor, e.g. 10 for 90%), or
                ``"actuarial"`` (equal present value at ``insurance.pension.lump_sum_interest_rate``
                with the spouse's age). None keeps the full benefit (no reduction).
            employee_basis: After-tax employee contributions: recovered tax-free over the Simplified
                Method's number of payments (IRS Pub. 575), then the benefit is fully taxable.
            lump_sum: Take the benefit as a lump sum at the start age instead of an annuity.
            lump_sum_amount: The plan's stated lump sum (else its present value at
                ``lump_sum_rate_pct``, default the configured rate, over the owner's life expectancy).
            rollover_account: An IRA (or other account) the lump sum is rolled into (not taxed);
                otherwise it is paid to the bank and taxed as a pension distribution.

        Raises:
            ValueError: If only one of ``benefit_multiplier_pct`` / ``final_salary_annual`` (or
                ``salary_history``) is given.
        """
        person, benefit_amount, cola_percent, survivor_percent = owner, benefit_annual, cola_pct, survivor_pct
        benefit_multiplier, final_salary = benefit_multiplier_pct, final_salary_annual
        super().__init__(person, company)
        if benefit_multiplier is not None and final_salary is None and salary_history:
            final_salary = self._final_average(salary_history, final_average_years)
        if (benefit_multiplier is None) != (final_salary is None):
            raise ValueError("benefit_multiplier and final_salary (or salary_history) must be given together")
        if early_reduction_pct_per_year and normal_retirement_age is None:
            raise ValueError("early_reduction_pct_per_year needs normal_retirement_age")
        if isinstance(survivor_reduction, str) and survivor_reduction != "actuarial":
            raise ValueError("survivor_reduction must be a percent, 'actuarial' or None")
        self.vesting_years = vesting_years
        self.years_of_service = vesting_years if years_of_service is None else years_of_service
        if benefit_multiplier is not None and final_salary is not None:
            benefit_amount = self.years_of_service * (benefit_multiplier / 100) * final_salary
        self.benefit_multiplier = benefit_multiplier
        self.final_salary = final_salary
        self.benefit_amount = benefit_amount
        self.start_age = start_age
        self.cola_percent = cola_percent
        self.survivor_percent = survivor_percent
        self.stat_pension_income = 0.0
        self.job = job
        # False for a survivor's continued benefit (no service of its own).
        self.accrues_service = True
        self.salary_history: dict[int, float] = dict(salary_history or {})
        self.final_average_years = final_average_years
        self.normal_retirement_age = normal_retirement_age
        self.early_reduction_pct_per_year = early_reduction_pct_per_year
        self.survivor_reduction = survivor_reduction
        self.employee_basis = float(employee_basis)
        self.lump_sum = lump_sum
        self.lump_sum_amount = lump_sum_amount
        self.lump_sum_rate_pct = lump_sum_rate_pct
        self.rollover_account = rollover_account
        #: The factor fixed when payments start (early-retirement and survivor reductions; 1 before).
        self.commencement_factor: float | None = None
        #: Basis still to recover and the tax-free part of each monthly payment (Simplified Method).
        self.remaining_basis = self.employee_basis
        self.monthly_exclusion = 0.0
        #: True once a lump sum has been paid (the plan owes nothing more).
        self.paid_out = False
        #: A surviving spouse's continued benefit (no reductions of its own at commencement).
        self.is_survivor_stream = False

        # Register so the owner (and estate/death handling) can find this pension.
        self.model.registries.pensions.register(person, self)

    @staticmethod
    def _final_average(history: "dict[int, float]", window: int | None) -> float:
        """The highest average of ``window`` consecutive years of ``history`` (the latest year without a
        window; every year when there are fewer)."""
        years = sorted(history)
        if not years:
            return 0.0
        if not window:
            return float(history[years[-1]])
        values = [history[y] for y in years]
        if len(values) <= window:
            return sum(values) / len(values)
        return max(sum(values[k : k + window]) / window for k in range(len(values) - window + 1))

    @property
    def is_vested(self) -> bool:
        """Whether the participant has met the vesting requirement."""
        return self.years_of_service >= self.vesting_years

    def is_eligible(self) -> bool:
        """Check if the person is currently eligible to receive benefits.

        Requires vesting. Then eligible once the person reaches ``start_age`` when set, otherwise
        once retired.
        """
        if not self.is_vested or self.paid_out:
            return False
        if self.start_age is not None:
            return self.person.age_years_fractional >= self.start_age
        return self.person.is_retired

    def sponsoring_job(self) -> "Job | None":
        """The job whose service accrues to this pension (explicit ``job``, else matched by company)."""
        if self.job is not None:
            return self.job
        for job in self.person.jobs:
            if job.company == self.company:
                return job
        return None

    def accrue_service(self) -> None:
        """Credit this year's service if the sponsoring job paid the participant this year."""
        if not self.accrues_service:
            return
        job = self.sponsoring_job()
        if job is None or getattr(job, "_booked_year", None) != self.model.year:
            return
        self.years_of_service += 1
        self.salary_history[self.model.year] = job.salary.base
        if self.benefit_multiplier is not None:
            if self.final_average_years:
                self.final_salary = self._final_average(self.salary_history, self.final_average_years)
            else:
                self.final_salary = job.salary.base
            self.benefit_amount = self.years_of_service * (self.benefit_multiplier / 100) * self.final_salary

    # --- commencement: reductions, the Simplified Method, a lump sum ---

    def early_retirement_factor(self, age: float) -> float:
        """The benefit factor for starting at ``age`` (1 at or after the normal retirement age)."""
        if self.normal_retirement_age is None or age >= self.normal_retirement_age:
            return 1.0
        years_early = round((self.normal_retirement_age - age) * 12) / 12
        return max(0.0, 1 - self.early_reduction_pct_per_year / 100 * years_early)

    def survivor_factor(self) -> float:
        """The retiree's benefit factor for the survivor election (1 without one)."""
        if not self.survivor_percent or self.survivor_reduction is None:
            return 1.0
        if self.survivor_reduction != "actuarial":
            return max(0.0, 1 - float(self.survivor_reduction) / 100)
        spouse = self.person.spouse
        if spouse is None:
            return 1.0
        from ..insurance.annuity import AnnuityPayoutType, calculate_annuity_factor

        rate = self.model.config.insurance.pension.lump_sum_interest_rate
        gender = getattr(self.person, "gender", None)
        single = calculate_annuity_factor(
            self.person.age, rate, AnnuityPayoutType.LIFE_ONLY, gender=gender, config=self.model.config
        )
        joint = calculate_annuity_factor(
            self.person.age,
            rate,
            AnnuityPayoutType.JOINT_AND_SURVIVOR,
            gender=gender,
            config=self.model.config,
            joint_age=spouse.age,
            joint_gender=getattr(spouse, "gender", None),
            survivor_percent=self.survivor_percent,
        )
        return single / joint if joint > 0 else 1.0

    def _expected_payments(self) -> int:
        """The Simplified Method's number of anticipated payments (IRS Pub. 575 Table 1 or 2)."""
        cfg = self.model.config.insurance.pension
        spouse = self.person.spouse
        if self.survivor_percent and spouse is not None:
            combined = self.person.age + spouse.age
            return next(n for limit, n in cfg.simplified_method_joint if combined <= limit)
        return next(n for limit, n in cfg.simplified_method_single if self.person.age <= limit)

    def _commence(self) -> None:
        """Fix the benefit when payments start: early-retirement and survivor reductions, the tax-free
        part of each payment, or the lump sum."""
        factor = 1.0
        if not self.is_survivor_stream:
            factor = self.early_retirement_factor(self.person.age_years_fractional) * self.survivor_factor()
        self.commencement_factor = factor
        if self.employee_basis > 0:
            self.monthly_exclusion = self.employee_basis / self._expected_payments()
        if self.lump_sum:
            self._pay_lump_sum()

    def _pay_lump_sum(self) -> None:
        from ..insurance.annuity import AnnuityPayoutType, calculate_annuity_factor

        amount = self.lump_sum_amount
        if amount is None:
            rate = self.lump_sum_rate_pct
            if rate is None:
                rate = self.model.config.insurance.pension.lump_sum_interest_rate
            monthly = self.benefit_amount * (self.commencement_factor or 1.0) / 12
            amount = monthly * calculate_annuity_factor(
                self.person.age,
                rate,
                AnnuityPayoutType.LIFE_ONLY,
                gender=getattr(self.person, "gender", None),
                config=self.model.config,
            )
        cause = f"{self.company} pension lump sum"
        if self.rollover_account is not None:
            # A direct rollover: not taxed, the money lands in the account.
            account = self.rollover_account
            account.balance += amount
            self.model.ledger.post(
                amount,
                FlowKind.BENEFIT,
                to_account=account,
                source=f"{self.company} pension plan",
                cause=cause,
                agent=self.person,
            )
        else:
            taxable = max(0.0, amount - self.remaining_basis)
            self.person.income.add(IncomeType.PENSION, taxable, source="pension")
            self.person.receive_cash(amount, source=f"{self.company} pension", kind=FlowKind.BENEFIT, cause=cause)
            # The 10% additional tax applies before 59.5 unless separated from service in or after the year
            # the participant turns 55 (IRC §72(t)(2)(A)(v)); the engine assumes that exception applies.
        self.remaining_basis = 0.0
        self.paid_out = True
        self.stat_pension_income = snap_money(self.stat_pension_income + amount)

    def get_annual_benefit(self) -> float:
        """Calculate the annual benefit amount payable this year (0 if not yet eligible)."""
        if self.is_eligible():
            return self.benefit_amount * (self.commencement_factor if self.commencement_factor is not None else 1.0)
        return 0.0

    def pre_step(self):
        # Deposit the month's benefit and record it as ordinary (non-FICA) income once eligible.
        # This mirrors the SocialSecurity agent: benefit -> income ledger + cash. Nothing here reads
        # other income, so its order relative to wages and Social Security (also 0) does not matter.
        if self.paid_out or not self.is_eligible():
            return
        if self.commencement_factor is None:
            self._commence()
            if self.paid_out:
                return
        benefit = self.get_annual_benefit() / 12
        if benefit > 0:
            excluded = min(self.monthly_exclusion, self.remaining_basis, benefit)
            self.remaining_basis -= excluded
            self.stat_pension_income = snap_money(self.stat_pension_income + benefit)
            self.person.income.add(IncomeType.PENSION, benefit - excluded, source="pension")
            self.person.receive_cash(benefit, source=f"{self.company} pension", kind=FlowKind.BENEFIT)

    def on_year_end(self):
        # Service for a year worked at the sponsor (after the year's payroll, before the salary
        # escalator, so "final salary" is this year's).
        self.accrue_service()
        # Compound the cost-of-living adjustment while the benefit is in pay so it keeps pace with
        # inflation over a long retirement.
        if self.cola_percent and self.is_eligible():
            self.benefit_amount *= 1 + self.cola_percent / 100.0

    def _repr_html_(self):
        desc = "<ul>"
        desc += f"<li>Company: {html.escape(self.company)}</li>"
        desc += f"<li>Vesting Years: {self.vesting_years}</li>"
        desc += f"<li>Years of Service: {self.years_of_service}</li>"
        desc += f"<li>Benefit Amount: ${self.benefit_amount:,.2f}</li>"
        if self.start_age is not None:
            desc += f"<li>Start Age: {self.start_age}</li>"
        if self.cola_percent:
            desc += f"<li>COLA: {self.cola_percent}%</li>"
        if self.survivor_percent:
            desc += f"<li>Survivor Benefit: {self.survivor_percent}%</li>"
        desc += "</ul>"
        return desc
