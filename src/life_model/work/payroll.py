# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pre-tax payroll deductions of a W-2 job (Plan 27 D3's ``Payroll``).

What a pay stub shows between gross pay and take-home pay, other than the 401(k) (which belongs to the
plan, ``Job401kAccount``). Each item's tax and cash treatment:

* ``health_premium_monthly``, ``dental_vision_monthly``: excluded from wages (box 1) and FICA wages (a
  §125 cafeteria plan); out of each paycheck, a premium paid to the employer's plan.
* ``fsa_annual`` (health FSA): excluded from both, up to the year's §125(i) limit; cash is unchanged (the
  FSA pays medical bills the household's spending already carries).
* ``dependent_care_fsa_annual``: excluded from both (box 10); cash unchanged (it pays the care bill); the
  part over the Form 2441 exclusion is added back at settlement.
* ``hsa_employee_annual``: excluded from both (§125; box 12 code W); out of each paycheck into the owner's
  first HSA, within the HSA limit.
* ``hsa_employer_annual``: never wages (box 12 code W); into the owner's HSA a twelfth a month while the
  job pays, so it stops with the job.
* ``commuter_monthly``: excluded from both up to the year's §132(f) monthly limit (the excess is wages);
  cash unchanged (the benefit pays the commute the household's spending already carries).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PayrollDeductions:
    """A job's pre-tax payroll deductions (see the module docstring for each item's treatment)."""

    #: Dependent care FSA election (W-2 box 10), per year.
    dependent_care_fsa_annual: float = 0.0
    #: Employee share of the employer health premium, per month (pre-tax, §125).
    health_premium_monthly: float = 0.0
    #: Dental and vision premiums, per month (pre-tax, §125).
    dental_vision_monthly: float = 0.0
    #: Health FSA election, per year (capped at the year's §125(i) limit).
    fsa_annual: float = 0.0
    #: Employee HSA contributions through payroll, per year (within the HSA limit).
    hsa_employee_annual: float = 0.0
    #: Employer HSA contributions, per year (paid a twelfth a month while the job pays).
    hsa_employer_annual: float = 0.0
    #: Qualified transportation (transit / parking) through payroll, per month.
    commuter_monthly: float = 0.0

    def __post_init__(self):
        for name in (
            "dependent_care_fsa_annual",
            "health_premium_monthly",
            "dental_vision_monthly",
            "fsa_annual",
            "hsa_employee_annual",
            "hsa_employer_annual",
            "commuter_monthly",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def premiums_monthly(self) -> float:
        """Pre-tax premiums out of each paycheck (health plus dental/vision)."""
        return self.health_premium_monthly + self.dental_vision_monthly
