# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Actual records for a simulated year (Plan 29 D1): what the household's real documents say.

``HouseholdSpec.actuals`` maps a tax year to an :class:`ActualRecords`: the filed Form 1040 and its
schedules (by the official line numbers of that year), W-2s, 1099s, the state return, a paystub,
year-end statement balances and a few spending totals. The builder ignores them; ``life-model
reconcile`` (:mod:`life_model.reconciliation`) compares them with the simulated year. Real documents
belong in ``my-models/`` (git-ignored), never in a tracked file.

Line names are the official ones for the year (:data:`FORM_1040_LINES`, :data:`SCHEDULE_LINES`):
``"1a"``, ``"11"`` (2024) or ``"11a"`` (2025), ``"12e"``... Every amount is in dollars of that year,
as printed on the document (whole dollars on a filed return are fine; reconciliation tolerates the
rounding). The records may carry lines the engine cannot simulate yet (withholding, Form 8606 basis,
payroll deductions, 1099-B cost basis): the reconciliation report classifies those as ``timing`` or
``missing_input`` instead of failing.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .schema import Identifier, NonNegativeMoney, SpecModel, spec_field

#: Money on a document; may be negative (a capital loss on line 7, a net operating loss).
Money = float

# --------------------------------------------------------------------------------------------------
# Official line names (read from the irs.gov PDFs of each year; the 2026 entries follow the IRS draft
# forms dated August 2026 and may change when the final forms are published)
# --------------------------------------------------------------------------------------------------

_1040_COMMON = {
    "1a": "Wages from Form(s) W-2, box 1",
    "1b": "Household employee wages",
    "1c": "Tip income not on line 1a",
    "1d": "Medicaid waiver payments",
    "1e": "Taxable dependent care benefits (Form 2441)",
    "1f": "Employer-provided adoption benefits (Form 8839)",
    "1g": "Wages from Form 8919",
    "1h": "Other earned income",
    "1i": "Nontaxable combat pay election",
    "1z": "Total of lines 1a-1h",
    "2a": "Tax-exempt interest",
    "2b": "Taxable interest",
    "3a": "Qualified dividends",
    "3b": "Ordinary dividends",
    "4a": "IRA distributions",
    "4b": "IRA distributions, taxable amount",
    "5a": "Pensions and annuities",
    "5b": "Pensions and annuities, taxable amount",
    "6a": "Social security benefits",
    "6b": "Social security benefits, taxable amount",
    "8": "Additional income from Schedule 1, line 10",
    "9": "Total income",
    "10": "Adjustments to income from Schedule 1, line 26",
    "16": "Tax",
    "17": "Amount from Schedule 2, line 3",
    "18": "Add lines 16 and 17",
    "19": "Child tax credit or credit for other dependents (Schedule 8812)",
    "20": "Amount from Schedule 3, line 8",
    "21": "Add lines 19 and 20",
    "22": "Subtract line 21 from line 18",
    "23": "Other taxes from Schedule 2, line 21",
    "25a": "Federal income tax withheld: Form(s) W-2",
    "25b": "Federal income tax withheld: Form(s) 1099",
    "25c": "Federal income tax withheld: other forms",
    "25d": "Total federal income tax withheld",
    "26": "Estimated tax payments and amount applied from the prior year",
    "28": "Additional child tax credit (Schedule 8812)",
    "29": "American opportunity credit (Form 8863)",
    "31": "Amount from Schedule 3, line 15",
    "33": "Total payments",
    "34": "Amount overpaid",
    "35a": "Amount refunded",
    "36": "Amount applied to next year's estimated tax",
    "37": "Amount you owe",
    "38": "Estimated tax penalty",
}

#: Form 1040 line number -> label, by tax year.
FORM_1040_LINES: dict[int, dict[str, str]] = {
    2024: {
        **_1040_COMMON,
        "7": "Capital gain or (loss)",
        "11": "Adjusted gross income",
        "12": "Standard deduction or itemized deductions",
        "13": "Qualified business income deduction",
        "14": "Add lines 12 and 13",
        "15": "Taxable income",
        "24": "Total tax",
        "27": "Earned income credit",
        "32": "Total other payments and refundable credits",
    },
    2025: {
        **_1040_COMMON,
        "7a": "Capital gain or (loss)",
        "11a": "Adjusted gross income",
        "11b": "Adjusted gross income (amount from line 11a)",
        "12e": "Standard deduction or itemized deductions",
        "13a": "Qualified business income deduction",
        "13b": "Additional deductions from Schedule 1-A, line 38",
        "14": "Add lines 12e, 13a and 13b",
        "15": "Taxable income",
        "24": "Total tax",
        "27a": "Earned income credit",
        "30": "Refundable adoption credit (Form 8839)",
        "32": "Total other payments and refundable credits",
    },
    2026: {
        **_1040_COMMON,
        "7a": "Capital gain or (loss)",
        "11a": "Adjusted gross income",
        "11b": "Adjusted gross income (amount from line 11a)",
        "12e": "Standard deduction or itemized deductions",
        "12f": "Charitable contribution deduction for non-itemizers",
        "13a": "Additional deductions from Schedule 1-A, line 44",
        "13b": "Qualified business income deduction",
        "14": "Add lines 12e, 12f, 13a and 13b",
        "15": "Taxable income",
        "24a": "Total tax",
        "24b": "Form 1062, line 15",
        "24c": "Add lines 24a and 24b",
        "27a": "Earned income credit",
        "30": "Refundable adoption credit (Form 8839)",
        "32a": "Total other payments and refundable credits",
        "32b": "Amount from Schedule 3-A",
        "32c": "Subtract line 32b from line 32a",
    },
}

_SCHEDULE_1 = {
    "1": "Taxable state/local refunds",
    "2a": "Alimony received",
    "3": "Business income (Schedule C)",
    "4": "Other gains or (losses) (Form 4797)",
    "5": "Rental real estate, royalties, partnerships (Schedule E)",
    "6": "Farm income (Schedule F)",
    "7": "Unemployment compensation",
    "8a": "Net operating loss",
    "8b": "Gambling",
    "8c": "Cancellation of debt",
    "8f": "Income from Form 8889 (HSA)",
    "8z": "Other income",
    "9": "Total other income",
    "10": "Additional income (to Form 1040 line 8)",
    "11": "Educator expenses",
    "13": "Health savings account deduction",
    "15": "Deductible part of self-employment tax",
    "16": "Self-employed SEP, SIMPLE and qualified plans",
    "17": "Self-employed health insurance deduction",
    "18": "Penalty on early withdrawal of savings",
    "19a": "Alimony paid",
    "20": "IRA deduction",
    "21": "Student loan interest deduction",
    "23": "Archer MSA deduction",
    "25": "Total other adjustments",
    "26": "Adjustments to income (to Form 1040 line 10)",
}
_SCHEDULE_2_2024 = {
    "1a": "Excess advance premium tax credit repayment (Form 8962)",
    "1z": "Additions to tax (premium tax credit repayment, ...)",
    "2": "Alternative minimum tax",
    "3": "Add lines 1z and 2 (to Form 1040 line 17)",
    "4": "Self-employment tax",
    "8": "Additional tax on IRAs or other tax-favored accounts (Form 5329)",
    "9": "Household employment taxes",
    "11": "Additional Medicare Tax (Form 8959)",
    "12": "Net investment income tax (Form 8960)",
    "17c": "Additional tax on HSA distributions",
    "21": "Total other taxes (to Form 1040 line 23)",
}
_SCHEDULE_2_2026 = {
    "1a": "Excess advance premium tax credit repayment (Form 8962)",
    "1z": "Additions to tax",
    "2": "Alternative minimum tax",
    "3": "Add lines 1z and 2 (to Form 1040 line 17)",
    "4": "Self-employment tax",
    "5": "Additional tax on IRAs or other tax-favored accounts (Form 5329)",
    "6": "Net investment income tax (Form 8960)",
    "11": "Additional Medicare Tax on self-employment income",
    "13c": "Additional tax on HSA distributions",
    "15": "Total additional income taxes",
    "17b": "Additional Medicare Tax on Medicare wages (Form 8959)",
    "20": "Total additional employment and other taxes",
    "21": "Total additional taxes (to Form 1040 line 23)",
}
_SCHEDULE_3 = {
    "1": "Foreign tax credit",
    "2": "Child and dependent care credit",
    "3": "Education credits",
    "4": "Retirement savings contributions credit",
    "5a": "Residential clean energy credit",
    "6b": "Credit for prior year minimum tax (Form 8801)",
    "7": "Total other nonrefundable credits",
    "8": "Nonrefundable credits (to Form 1040 line 20)",
    "9": "Net premium tax credit",
    "11": "Excess social security and tier 1 RRTA tax withheld",
    "15": "Other payments and refundable credits (to Form 1040 line 31)",
}
_SCHEDULE_A = {
    "1": "Medical and dental expenses",
    "4": "Deductible medical and dental expenses",
    "5a": "State and local income or sales taxes",
    "5b": "State and local real estate taxes",
    "5d": "Total of lines 5a-5c",
    "5e": "State and local taxes after the cap",
    "7": "Total taxes",
    "8a": "Home mortgage interest on Form 1098",
    "8e": "Total home mortgage interest",
    "10": "Total interest",
    "11": "Gifts by cash or check",
    "12": "Gifts other than by cash or check",
    "14": "Total gifts to charity",
    "17": "Total itemized deductions",
}
_SCHEDULE_B = {"2": "Total interest", "4": "Taxable interest (to Form 1040 line 2b)", "6": "Ordinary dividends"}
_SCHEDULE_D = {
    "6": "Short-term capital loss carryover",
    "7": "Net short-term capital gain or (loss)",
    "13": "Capital gain distributions",
    "14": "Long-term capital loss carryover",
    "15": "Net long-term capital gain or (loss)",
    "16": "Combine lines 7 and 15",
    "21": "Capital loss allowed (up to $3,000)",
}
_SCHEDULE_1A_2025 = {
    "13": "Qualified tips deduction",
    "21": "Qualified overtime deduction",
    "30": "Qualified car loan interest deduction",
    "37": "Enhanced deduction for seniors",
    "38": "Total additional deductions (to Form 1040 line 13b)",
}
_SCHEDULE_1A_2026 = {
    "15": "Qualified tips deduction",
    "27": "Qualified overtime deduction",
    "36": "Qualified car loan interest deduction",
    "43": "Enhanced deduction for seniors",
    "44": "Total additional deductions (to Form 1040 line 13a)",
}

#: The forms and schedules Plan 31 added (same line numbers 2024-2026 for the lines read).
_PLAN_31_FORMS = {
    "C": {"31": "Net profit or (loss)"},
    "SE": {
        "2": "Net profit from Schedule C",
        "3": "Combine lines 1a, 1b and 2",
        "4a": "Line 3 x 92.35%",
        "4c": "Combine lines 4a and 4b",
        "6": "Add lines 4c and 5b",
        "12": "Self-employment tax",
        "13": "Deduction for one-half of self-employment tax",
    },
    "8812": {"14": "Child tax credit and credit for other dependents", "27": "Additional child tax credit"},
    "2441": {"11": "Credit for child and dependent care expenses", "26": "Taxable dependent care benefits"},
    "8863": {"8": "Refundable American opportunity credit", "19": "Nonrefundable education credits"},
    "8880": {"12": "Credit for qualified retirement savings contributions"},
    "8995": {"1": "Qualified business income", "15": "Qualified business income deduction"},
    "6251": {"4": "Alternative minimum taxable income", "9": "Tentative minimum tax", "11": "Alternative minimum tax"},
    "8814": {"15": "Tax on the child's income (to Form 1040 line 16)"},
    # Plan 31 tasks 6-7
    "8962": {
        "1": "Tax family size",
        "3": "Household income",
        "4": "Federal poverty line",
        "5": "Household income as a percentage of the federal poverty line",
        "7": "Applicable figure",
        "8a": "Annual contribution amount",
        "8b": "Monthly contribution amount",
        "11a": "Annual enrollment premiums",
        "11b": "Annual applicable SLCSP premium",
        "11d": "Annual maximum premium assistance",
        "11e": "Annual premium tax credit allowed",
        "11f": "Annual advance payment of PTC",
        "24": "Total premium tax credit",
        "25": "Advance payment of PTC",
        "26": "Net premium tax credit",
        "27": "Excess advance premium tax credit",
        "28": "Repayment limitation",
        "29": "Excess advance premium tax credit repayment",
    },
    "2210": {
        "4": "Current year tax",
        "6": "Withholding taxes",
        "8": "Maximum required annual payment based on prior year's tax",
        "9": "Required annual payment",
        "19": "Penalty",
    },
}

#: Schedule name -> line -> label, by tax year (the lines reconciliation reads; others are accepted).
SCHEDULE_LINES: dict[int, dict[str, dict[str, str]]] = {
    2024: {
        "1": _SCHEDULE_1,
        "2": _SCHEDULE_2_2024,
        "3": _SCHEDULE_3,
        "A": _SCHEDULE_A,
        "B": _SCHEDULE_B,
        "D": _SCHEDULE_D,
        **_PLAN_31_FORMS,
    },
    2025: {
        "1": _SCHEDULE_1,
        "1-A": _SCHEDULE_1A_2025,
        "2": _SCHEDULE_2_2024,
        "3": _SCHEDULE_3,
        "A": _SCHEDULE_A,
        "B": _SCHEDULE_B,
        "D": _SCHEDULE_D,
        **_PLAN_31_FORMS,
    },
    2026: {
        "1": _SCHEDULE_1,
        "1-A": _SCHEDULE_1A_2026,
        "2": _SCHEDULE_2_2026,
        "3": _SCHEDULE_3,
        "A": _SCHEDULE_A,
        "B": _SCHEDULE_B,
        "D": _SCHEDULE_D,
        **_PLAN_31_FORMS,
    },
}

#: Form W-2 boxes.
W2_BOXES: dict[str, str] = {
    "1": "Wages, tips, other compensation",
    "2": "Federal income tax withheld",
    "3": "Social security wages",
    "4": "Social security tax withheld",
    "5": "Medicare wages and tips",
    "6": "Medicare tax withheld",
    "7": "Social security tips",
    "10": "Dependent care benefits",
    "16": "State wages",
    "17": "State income tax",
}

#: Information returns: form -> box -> label.
FORM_1099_BOXES: dict[str, dict[str, str]] = {
    "1099-INT": {
        "1": "Interest income",
        "3": "Interest on U.S. Savings Bonds and Treasuries",
        "4": "Federal tax withheld",
        "8": "Tax-exempt interest",
    },
    "1099-DIV": {
        "1a": "Total ordinary dividends",
        "1b": "Qualified dividends",
        "2a": "Total capital gain distributions",
        "4": "Federal tax withheld",
    },
    "1099-B": {
        "1d": "Proceeds",
        "1e": "Cost or other basis",
        "1g": "Wash sale loss disallowed",
        "4": "Federal tax withheld",
    },
    "1099-R": {"1": "Gross distribution", "2a": "Taxable amount", "4": "Federal tax withheld"},
    "SSA-1099": {
        "3": "Benefits paid",
        "4": "Benefits repaid",
        "5": "Net benefits",
        "6": "Voluntary federal tax withheld",
    },
    "1098": {"1": "Mortgage interest received", "10": "Other (property tax paid from escrow)"},
    "1098-E": {"1": "Student loan interest received"},
    "5498": {"1": "IRA contributions", "5": "Fair market value of account"},
    "8606": {"2": "Basis in traditional IRAs", "14": "Total basis"},
}

#: The tax years with line tables.
LINE_TABLE_YEARS: tuple[int, ...] = tuple(sorted(FORM_1040_LINES))


def line_table_year(year: int) -> int:
    """The line table that applies to ``year`` (the nearest published one)."""
    if year in FORM_1040_LINES:
        return year
    return LINE_TABLE_YEARS[0] if year < LINE_TABLE_YEARS[0] else LINE_TABLE_YEARS[-1]


# --------------------------------------------------------------------------------------------------
# The records
# --------------------------------------------------------------------------------------------------


class W2(SpecModel):
    """One Form W-2."""

    person: Identifier | None = spec_field(None, description="Person id of the employee (the only adult when unset).")
    employer: str = spec_field(description="Employer name (matches the job's company).")
    boxes: dict[str, Money] = spec_field(
        default_factory=dict, description="Box number -> amount, e.g. {'1': 85000, '2': 9100, '3': 92000}.", unit="USD"
    )
    box12: dict[str, Money] = spec_field(
        default_factory=dict,
        description="Box 12 code -> amount, e.g. {D: 7000} (pre-tax 401k), AA (Roth 401k), W (HSA).",
        unit="USD",
    )


class InformationReturn(SpecModel):
    """A 1099 (or 1098, 5498, Form 8606): ``form`` plus box amounts."""

    form: Literal["1099-INT", "1099-DIV", "1099-B", "1099-R", "SSA-1099", "1098", "1098-E", "5498", "8606"] = (
        spec_field(description="Which form.")
    )
    person: Identifier | None = spec_field(None, description="Recipient's person id.")
    payer: str | None = spec_field(None, description="Payer / institution name.")
    account: Identifier | None = spec_field(
        None, description="Id of the spec account or debt it reports on (lets reconcile compare that account's flows)."
    )
    boxes: dict[str, Money] = spec_field(default_factory=dict, description="Box -> amount.", unit="USD")
    code: str | None = spec_field(None, description="1099-R box 7 distribution code; 1099-B short/long term.")


class StateReturnActuals(SpecModel):
    """The filed state return."""

    state: str = spec_field(description="Two-letter state.")
    agi: Money | None = spec_field(None, description="State AGI / income.", unit="USD")
    taxable_income: Money | None = spec_field(None, description="State taxable income.", unit="USD")
    tax: Money | None = spec_field(None, description="State income tax (before payments).", unit="USD")
    withheld: Money | None = spec_field(None, description="State tax withheld.", unit="USD")
    lines: dict[str, Money] = spec_field(default_factory=dict, description="Other lines by the state form's numbers.")


class Paystub(SpecModel):
    """A representative paystub, converted to monthly amounts."""

    person: Identifier | None = spec_field(None, description="Employee's person id.")
    employer: str | None = spec_field(None, description="Employer name.")
    gross_monthly: NonNegativeMoney | None = spec_field(None, description="Gross pay.", unit="USD/month")
    pretax_deductions_monthly: dict[str, NonNegativeMoney] = spec_field(
        default_factory=dict,
        description="Pre-tax deductions by name: 401k, roth_401k, health, dental_vision, hsa, fsa, dependent_care_fsa, "
        "commuter.",
        unit="USD/month",
    )
    federal_withholding_monthly: NonNegativeMoney | None = spec_field(
        None, description="Federal withholding.", unit="USD/month"
    )
    net_monthly: NonNegativeMoney | None = spec_field(None, description="Net pay.", unit="USD/month")


class ReturnActuals(SpecModel):
    """One filed federal return: the Form 1040 lines, its schedules and the state return."""

    filer: Identifier | None = spec_field(
        None,
        description="Person id of the primary filer (the unit head). Optional when the household files one return.",
    )
    form_1040: dict[str, Money] = spec_field(
        default_factory=dict,
        description="Form 1040 line -> amount, by that year's line numbers ('1a', '11', '12e').",
        unit="USD",
    )
    schedules: dict[str, dict[str, Money]] = spec_field(
        default_factory=dict,
        description="Schedule ('1', '1-A', '2', '3', 'A', 'B', 'D') -> line -> amount.",
        unit="USD",
    )
    state_return: StateReturnActuals | None = spec_field(None, description="The state return.")


class SpendingActuals(SpecModel):
    """Year totals from bank/card statements, for calibration against the model's assumptions (D6)."""

    living_annual: NonNegativeMoney | None = spec_field(None, description="Living spending.", unit="USD/year")
    medical_out_of_pocket_annual: NonNegativeMoney | None = spec_field(
        None, description="Out-of-pocket medical.", unit="USD/year"
    )
    medicare_premiums_annual: NonNegativeMoney | None = spec_field(
        None, description="Medicare premiums.", unit="USD/year"
    )
    dependent_costs_annual: NonNegativeMoney | None = spec_field(
        None, description="Child and dependent costs.", unit="USD/year"
    )
    housing_annual: NonNegativeMoney | None = spec_field(
        None, description="Rent / mortgage / property costs.", unit="USD/year"
    )


class ActualRecords(SpecModel):
    """What the household's documents say about one tax year (``actuals[year]``)."""

    form_1040: dict[str, Money] = spec_field(
        default_factory=dict,
        description="The household's Form 1040 lines when it files one return (else use 'returns').",
        unit="USD",
    )
    schedules: dict[str, dict[str, Money]] = spec_field(
        default_factory=dict, description="Schedules of that single return: schedule -> line -> amount.", unit="USD"
    )
    state_return: StateReturnActuals | None = spec_field(None, description="State return of that single return.")
    returns: list[ReturnActuals] = spec_field(
        default_factory=list, description="One entry per filed return (separate filers, several single adults)."
    )
    w2: list[W2] = spec_field(default_factory=list, description="Forms W-2.")
    form_1099: list[InformationReturn] = spec_field(default_factory=list, description="1099s, 1098s, 5498s, Form 8606.")
    paystub: list[Paystub] = spec_field(default_factory=list, description="Representative paystubs.")
    balances: dict[Identifier, NonNegativeMoney] = spec_field(
        default_factory=dict,
        description="Year-end (December 31) statement balances by spec account or debt id (debts as positive balances).",
        unit="USD",
    )
    spending: SpendingActuals | None = spec_field(None, description="Spending totals for calibration.")
    notes: str | None = spec_field(None, description="Free text.")

    @model_validator(mode="after")
    def _one_return_form(self) -> "ActualRecords":
        if self.returns and (self.form_1040 or self.schedules or self.state_return is not None):
            raise ValueError("give the return lines either at the top level (one return) or in 'returns', not both")
        return self

    def all_returns(self) -> list[ReturnActuals]:
        """Every return's records (the top-level lines become one unnamed return)."""
        if self.returns:
            return list(self.returns)
        if self.form_1040 or self.schedules or self.state_return is not None:
            return [ReturnActuals(form_1040=self.form_1040, schedules=self.schedules, state_return=self.state_return)]
        return []


#: ``HouseholdSpec.actuals`` value type: tax year -> records.
ActualsByYear = dict[Annotated[int, Field(ge=1900, le=2200)], ActualRecords]


def unknown_lines(records: ActualRecords, year: int) -> list[tuple[str, str]]:
    """``(path, line)`` for every return line that is not a line of that year's forms."""
    table_year = line_table_year(year)
    lines_1040 = FORM_1040_LINES[table_year]
    schedules = SCHEDULE_LINES[table_year]
    problems = []
    for index, tax_return in enumerate(records.all_returns()):
        prefix = f"returns[{index}]." if records.returns else ""
        for line in tax_return.form_1040:
            if line not in lines_1040:
                problems.append((f"{prefix}form_1040.{line}", line))
        for name in tax_return.schedules:
            if name not in schedules:
                problems.append((f"{prefix}schedules.{name}", name))
    return problems
