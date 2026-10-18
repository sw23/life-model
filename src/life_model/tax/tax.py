# Copyright 2023 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .brackets import bracket_slices
from .federal import (
    FilingStatus,
    capital_gains_tax,
    federal_income_tax,
    get_federal_tax_brackets,
    net_investment_income_tax,
)
from .fica import (
    get_medicare_additional_rate,
    get_medicare_additional_rate_threshold,
    get_medicare_rate,
    social_security_tax,
)
from .state import state_income_tax

if TYPE_CHECKING:
    from ..config.financial_config import FinancialConfig


class TaxesDue:
    def __init__(
        self,
        federal: float = 0,
        state: float = 0,
        ss: float = 0,
        medicare: float = 0,
        credits: float = 0.0,
        niit: float = 0.0,
    ):
        """Taxes due for the year, split up by type of tax.

        ``credits`` holds tax credits (e.g. the Child Tax Credit) that reduce the total. A
        refundable credit may exceed the federal liability, driving ``total`` negative (a refund).
        ``niit`` is the §1411 net investment income surtax, tracked separately from ``federal``
        because it has its own base and its own unindexed thresholds.

        Besides the totals, :func:`compute_taxes` and ``TaxUnit.get_income_taxes_due`` record the
        intermediate figures they computed the totals from (the attributes below), so a tax return
        record can be built from exactly the numbers settlement used without recomputing anything.
        """
        self.federal = federal
        self.state = state
        self.ss = ss
        self.medicare = medicare
        self.credits = credits
        self.niit = niit

        #: Ordinary income plus preferential income before deductions (the return's AGI base).
        self.total_income = 0.0
        #: Deductions applied (the larger of standard / itemized, plus any senior deduction).
        self.deductions = 0.0
        #: ``max(total_income - deductions, 0)``.
        self.taxable_income = 0.0
        #: The part of ``taxable_income`` taxed on the ordinary brackets.
        self.taxable_ordinary = 0.0
        #: The part of ``taxable_income`` taxed on the preferential (capital-gains) schedule.
        self.taxable_preferential = 0.0
        #: Tax on ``taxable_ordinary`` from the ordinary brackets.
        self.ordinary_tax = 0.0
        #: Tax on ``taxable_preferential`` stacked above ordinary income.
        self.preferential_tax = 0.0
        #: The ordinary bracket segments reached: ``(lower, upper, rate_percent, amount, tax)``.
        self.ordinary_brackets: list[tuple[float, float, float, float, float]] = []
        #: Social Security tax per worker, in the order of the wage list passed in.
        self.ss_by_worker: list[float] = []
        #: Medicare tax per worker (base rate, plus that worker's wage-share of the additional tax).
        self.medicare_by_worker: list[float] = []
        #: Additional Medicare tax on combined wages over the filing-status threshold.
        self.additional_medicare = 0.0
        #: Standard deduction, itemized deductions and senior deduction the unit compared/added.
        self.standard_deduction = 0.0
        self.itemized_deduction = 0.0
        self.senior_deduction = 0.0
        #: Credits by name (``child_tax_credit`` ...); they sum to ``credits``.
        self.credits_detail: dict[str, float] = {}
        #: Nonrefundable / refundable split of ``credits``.
        self.nonrefundable_credits = 0.0
        self.refundable_credits = 0.0
        #: Additional taxes (early-withdrawal penalties) by source; included in ``federal``.
        self.penalties_detail: dict[str, float] = {}
        #: The state computation's breakdown (a :class:`~life_model.tax.state.StateTaxDetail`), when
        #: the caller resolved one.
        self.state_detail = None

    @property
    def penalties(self) -> float:
        """Additional taxes (penalties) included in ``federal``."""
        return sum(self.penalties_detail.values())

    @property
    def total(self) -> float:
        """Total taxes due for the year, net of credits (negative means a refund)."""
        return self.federal + self.state + self.ss + self.medicare + self.niit - self.credits


def compute_taxes(
    ordinary_income: float,
    deductions: float,
    filing_status: FilingStatus,
    wage_incomes: "Sequence[float]",
    config: "FinancialConfig | None" = None,
    *,
    credits: float = 0.0,
    state_tax: "float | None" = None,
    preferential_income: float = 0.0,
    net_investment_income: float = 0.0,
) -> TaxesDue:
    """Compute income and payroll taxes for a tax unit.

    Income tax is levied on the unit's combined ordinary income; FICA is levied **per person**
    on each worker's own wages. Keeping the two bases separate is what makes three payroll-tax
    details come out right:

    * FICA is not charged on 401k/IRA distributions (they are ordinary income, not wages).
    * The Social Security wage cap is applied per worker, not to the couple's combined wages, so
      two earners each below the cap pay Social Security on both full salaries.
    * The FICA base already includes pre-tax 401k deferrals (recorded as wages by ``Job``).

    Args:
        ordinary_income: Combined ordinary taxable income for the unit (income tax base).
        deductions: Deductions applied against ordinary income.
        filing_status: Filing status of the unit.
        wage_incomes: Each member's FICA-subject wages (payroll tax base), one entry per person.
        config: Per-model config. Defaults to the global config.
        credits: Pre-computed tax credits (e.g. Child Tax Credit) recorded on the result and
            subtracted from ``total``. Defaults to 0 (no credits).
        state_tax: Precomputed state income tax for the unit. When ``None`` the ``DEFAULT`` flat
            rate is applied to the federal AGI base. Callers that resolve a state pack compute
            state tax from the state base and pass it here so it can also be folded into the SALT
            itemized deduction without circularity.
        preferential_income: Long-term capital gains and qualified dividends, taxed on the
            preferential schedule stacked above ordinary income. Defaults to 0.
        net_investment_income: Investment income subject to the §1411 surtax. Defaults to 0.
    """
    # Deductions are applied to ordinary income first and spill onto the gain only once ordinary
    # income is exhausted — the clamp below is what makes a retiree living on gains alone come out
    # at $0 federal tax.
    total_income = ordinary_income + preferential_income
    taxable_income = max(total_income - deductions, 0)
    taxable_gains = max(0.0, min(preferential_income, taxable_income))
    taxable_ordinary = taxable_income - taxable_gains

    ordinary_tax = federal_income_tax(taxable_ordinary, filing_status, config)
    preferential_tax = capital_gains_tax(taxable_ordinary, taxable_gains, filing_status, config)
    tax_federal = ordinary_tax
    tax_federal += preferential_tax

    # The surtax is levied on the lesser of net investment income and the amount by which MAGI
    # exceeds the threshold. MAGI is a pre-deduction figure, unlike the taxable-income base above.
    tax_niit = net_investment_income_tax(net_investment_income, total_income, filing_status, config)

    if state_tax is None:
        # ``DEFAULT`` flat rate on the federal *taxable income* (post-deduction) base. (This local was
        # once named ``adjusted_gross_income``, which it never was: it is after deductions.)
        tax_state = state_income_tax(taxable_income, config)
    else:
        tax_state = state_tax

    # Social Security and base Medicare are per worker; the Additional Medicare surtax applies to
    # the unit's combined wages over the filing-status threshold.
    ss_by_worker = [social_security_tax(wages, config) for wages in wage_incomes]
    tax_ss = sum(ss_by_worker)
    medicare_rate = get_medicare_rate(config)
    medicare_by_worker = [wages * medicare_rate / 100 for wages in wage_incomes]
    tax_medicare = sum(medicare_by_worker)
    combined_wages = sum(wage_incomes)
    additional_threshold = get_medicare_additional_rate_threshold(filing_status, config)
    additional_medicare = 0.0
    if combined_wages > additional_threshold:
        additional_medicare = (combined_wages - additional_threshold) * get_medicare_additional_rate(config) / 100
        tax_medicare += additional_medicare
        # Attribute the surtax to workers by their share of the combined wages (reporting only).
        medicare_by_worker = [
            base + additional_medicare * wages / combined_wages
            for base, wages in zip(medicare_by_worker, wage_incomes, strict=True)
        ]
    if len(medicare_by_worker) == 1:
        medicare_by_worker = [tax_medicare]

    taxes = TaxesDue(tax_federal, tax_state, tax_ss, tax_medicare, credits=credits, niit=tax_niit)
    taxes.total_income = total_income
    taxes.deductions = deductions
    taxes.taxable_income = taxable_income
    taxes.taxable_ordinary = taxable_ordinary
    taxes.taxable_preferential = taxable_gains
    taxes.ordinary_tax = ordinary_tax
    taxes.preferential_tax = preferential_tax
    taxes.ordinary_brackets = bracket_slices(taxable_ordinary, get_federal_tax_brackets(filing_status, config))
    taxes.ss_by_worker = ss_by_worker
    taxes.medicare_by_worker = medicare_by_worker
    taxes.additional_medicare = additional_medicare
    if credits:
        taxes.credits_detail = {"credits": credits}
    return taxes


def get_income_taxes_due(
    gross_income: float,
    deductions: float,
    filing_status: FilingStatus,
    config: "FinancialConfig | None" = None,
) -> TaxesDue:
    """Gets income taxes due for a single earner whose entire income is wages.

    This is a convenience wrapper around :func:`compute_taxes` that treats ``gross_income`` as
    both the ordinary income tax base and a single worker's FICA wages. Multi-person units and
    units with non-wage income should use :func:`compute_taxes` (via ``TaxUnit``) so that FICA is
    computed per person on wages only.

    Args:
        gross_income (float): Income subject to income and payroll taxes.
        deductions (float): Deductions from income.
        filing_status (FilingStatus): Filing status.
        config (FinancialConfig, optional): Per-model config. Defaults to the global config.

    Returns:
        TaxesDue: Taxes due, split by type.
    """
    return compute_taxes(gross_income, deductions, filing_status, [gross_income], config)
