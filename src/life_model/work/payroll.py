# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Pre-tax payroll deductions of a W-2 job (Plan 27 D3's ``Payroll``; Plan 31 lands the first field).

Only the dependent-care FSA is modeled so far (it drives the Form 2441 exclusion and the dependent care
credit). Plan 27 adds the health / dental / vision premiums, the health FSA, employee and employer HSA
and commuter benefits to this same object.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PayrollDeductions:
    """A job's pre-tax payroll deductions (dollars per year).

    ``dependent_care_fsa_annual`` is the dependent care FSA election (IRC §129): left out of W-2 box 1
    and of Social Security and Medicare wages, reported in box 10. It pays the household's dependent
    care (so cash flow is unchanged: pay is lower by the election and the care bill by the same
    amount); the part over the year's Form 2441 exclusion is added back to wages at settlement.
    """

    #: Dependent care FSA election (W-2 box 10).
    dependent_care_fsa_annual: float = 0.0

    def __post_init__(self):
        if self.dependent_care_fsa_annual < 0:
            raise ValueError("dependent_care_fsa_annual must be non-negative")
