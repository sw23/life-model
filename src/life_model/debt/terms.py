# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Loan terms from what a statement shows.

A loan statement shows some of: the original amount, the origination month, the original term, the
current balance, the months remaining and the monthly payment (principal and interest). With the
rate, a few of them determine the rest. :func:`resolve_loan_terms` fills in the missing ones and
refuses inputs that contradict each other, naming the field to recheck.

Conventions (see docs/units-and-conventions.md):

* Rates are APRs in percent; the monthly rate is ``APR / 12``.
* The first payment is in the month after origination, so a loan originated in 2024-03 has made 21
  payments (April 2024 through December 2025) when a run starts in January 2026, and the run's first
  month makes payment 22.
* ``payments_made`` counts scheduled payments; ``remaining_months`` counts the scheduled payments left
  to maturity, including the current month's.
* A current balance below the original schedule is a prepaid loan (it pays off early at the contract
  payment); a balance above it is an error (the terms are wrong, or payments were missed) unless the
  statement is trusted over the contract (``schedule="statement"``).

**Which fields to trust** (``schedule``). ``"contract"`` (default): the original terms define the
schedule and the statement must agree with them. ``"statement"``: the statement's current balance is
right even though it is above the original schedule (late payments, a deferral, a forbearance); the loan
amortizes from that balance at the statement's payment (``monthly_payment``), else over its
``remaining_months``, else at the contract payment of the original amount and term (it then pays off
later than the original maturity). The original amount, term and origination are kept for the record.
"""

#: ``schedule`` choices of :func:`resolve_loan_terms`.
SCHEDULES = ("contract", "statement")

import math
from dataclasses import dataclass


class LoanTermsError(ValueError):
    """Loan inputs that contradict each other. ``field`` is the input to recheck."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"{field}: {message}")


@dataclass(frozen=True)
class LoanTerms:
    """A loan's resolved terms (see :func:`resolve_loan_terms`)."""

    #: Amount originally borrowed (the current balance when the statement does not show it).
    original_amount: float
    #: Original term in months (payments made plus the months remaining).
    term_months: int
    #: Scheduled payments already made before the as-of month (0 for a new loan or when unknown).
    payments_made: int
    #: Principal owed at the as-of month, before its payment.
    current_balance: float
    #: Principal and interest per month.
    monthly_payment: float
    #: Origination ``(year, month)``, when known.
    origination: tuple[int, int] | None = None

    @property
    def remaining_months(self) -> int:
        return max(0, self.term_months - self.payments_made)


def monthly_rate(rate_pct: float) -> float:
    """The monthly rate (a fraction) of an APR in percent."""
    return rate_pct / 1200.0


def amortizing_payment(principal: float, rate_pct: float, months: int) -> float:
    """The level monthly payment that pays ``principal`` off in ``months`` payments."""
    if months <= 0:
        return principal
    i = monthly_rate(rate_pct)
    if i == 0:
        return principal / months
    growth = (1 + i) ** months
    return principal * i * growth / (growth - 1)


def scheduled_balance(original: float, rate_pct: float, payment: float, payments_made: int) -> float:
    """The balance after ``payments_made`` level payments of ``payment`` on ``original`` (never negative)."""
    i = monthly_rate(rate_pct)
    if i == 0:
        return max(0.0, original - payment * payments_made)
    growth = (1 + i) ** payments_made
    return max(0.0, original * growth - payment * (growth - 1) / i)


def months_to_pay_off(balance: float, rate_pct: float, payment: float) -> int | None:
    """Payments of ``payment`` needed to pay ``balance`` off (None when the payment never does)."""
    if balance <= 0:
        return 0
    i = monthly_rate(rate_pct)
    if i == 0:
        return math.ceil(balance / payment - 1e-9) if payment > 0 else None
    if payment <= balance * i:
        return None
    return math.ceil(-math.log(1 - balance * i / payment) / math.log(1 + i) - 1e-9)


def months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    """Calendar months from ``start`` to ``end`` (``(year, month)`` pairs)."""
    return (end[0] * 12 + end[1]) - (start[0] * 12 + start[1])


def parse_origination(value) -> tuple[int, int] | None:
    """``"YYYY-MM"``, ``(year, month)`` or a year (January) as ``(year, month)``; None passes through."""
    if value is None:
        return None
    if isinstance(value, tuple):
        return (int(value[0]), int(value[1]))
    if isinstance(value, int | float) and not isinstance(value, bool):
        return (int(value), 1)
    from ..model import parse_year_month

    return parse_year_month(str(value))


def resolve_loan_terms(
    *,
    rate_pct: float,
    as_of: tuple[int, int] | None = None,
    original_amount: float | None = None,
    term_months: int | None = None,
    origination=None,
    payments_made: int | None = None,
    remaining_months: int | None = None,
    current_balance: float | None = None,
    monthly_payment: float | None = None,
    names: dict[str, str] | None = None,
    schedule: str = "contract",
) -> LoanTerms:
    """Resolve a loan's terms from the inputs a statement shows.

    Args:
        rate_pct: APR in percent.
        as_of: ``(year, month)`` the balance is for (the month the loan enters the run); needed with
            ``origination``.
        original_amount, term_months, origination, payments_made: The loan as originated.
        remaining_months, current_balance, monthly_payment: The statement today (the payment is
            principal and interest).
        names: How to name each argument in an error (e.g. ``{"current_balance": "balance"}``).
        schedule: ``"contract"`` (the original terms rule) or ``"statement"`` (trust the statement's balance;
            see the module docstring).

    Returns:
        The resolved :class:`LoanTerms`.

    Raises:
        LoanTermsError: When the inputs are insufficient or disagree (``field`` names the input).
    """
    names = names or {}

    def name(arg: str) -> str:
        return names.get(arg, arg)

    origin = parse_origination(origination)
    if origin is not None:
        if as_of is None:
            raise LoanTermsError(name("origination"), "an origination month needs the as-of month of the balance")
        elapsed = months_between(origin, as_of)
        if elapsed < 0:
            raise LoanTermsError(
                name("origination"),
                f"{origin[0]}-{origin[1]:02d} is after the as-of month {as_of[0]}-{as_of[1]:02d}; a loan taken out "
                "later belongs in an event",
            )
        derived = max(0, elapsed - 1)
        if payments_made is not None and abs(payments_made - derived) > 1:
            raise LoanTermsError(
                name("payments_made"),
                f"{payments_made} payments disagree with origination {origin[0]}-{origin[1]:02d} "
                f"({derived} payments by {as_of[0]}-{as_of[1]:02d})",
            )
        payments_made = derived if payments_made is None else payments_made
    if term_months is not None and term_months < 0:
        raise LoanTermsError(name("term_months"), "must not be negative")
    if schedule not in SCHEDULES:
        raise ValueError(f"schedule must be one of {SCHEDULES}, got {schedule!r}")
    if schedule == "statement":
        return _resolve_from_statement(
            rate_pct=rate_pct,
            original_amount=original_amount,
            term_months=term_months,
            origin=origin,
            payments_made=payments_made,
            remaining_months=remaining_months,
            current_balance=current_balance,
            monthly_payment=monthly_payment,
            name=name,
        )

    # Months: payments made + remaining = term (one month of slack for the first-payment convention).
    if remaining_months is not None:
        if term_months is not None and payments_made is not None:
            if abs(payments_made + remaining_months - term_months) > 1:
                raise LoanTermsError(
                    name("remaining_months"),
                    f"{remaining_months} months remaining disagree with a {term_months}-month term and "
                    f"{payments_made} payments made ({term_months - payments_made} remaining)",
                )
            remaining_months = term_months - payments_made
        elif term_months is not None:
            payments_made = max(0, term_months - remaining_months)
        else:
            term_months = (payments_made or 0) + remaining_months
    elif term_months is not None and payments_made is not None:
        remaining_months = max(0, term_months - payments_made)

    if payments_made is not None and term_months is not None and payments_made > term_months:
        raise LoanTermsError(
            name("origination" if origin is not None else "payments_made"),
            f"{payments_made} payments made exceed the {term_months}-month term: the loan is already paid off",
        )

    # The contract payment, from the loan as originated.
    contract_payment = None
    if original_amount is not None and term_months is not None:
        contract_payment = amortizing_payment(original_amount, rate_pct, term_months)

    payment = monthly_payment
    if payment is None:
        if contract_payment is not None:
            payment = contract_payment
        elif current_balance is not None and remaining_months is not None:
            payment = amortizing_payment(current_balance, rate_pct, remaining_months)

    # The balance: the statement's, else the schedule's.
    schedule = None
    if original_amount is not None and payment is not None and payments_made is not None:
        schedule = scheduled_balance(original_amount, rate_pct, payment, payments_made)
    balance = current_balance
    if balance is None:
        if schedule is not None:
            balance = schedule
        elif original_amount is not None:
            balance = original_amount
        elif remaining_months is not None and payment is not None:
            # Three of balance / months / payment give the fourth: the balance the payment retires.
            i = monthly_rate(rate_pct)
            balance = payment * remaining_months if i == 0 else payment * (1 - (1 + i) ** -remaining_months) / i
        else:
            raise LoanTermsError(
                name("current_balance"),
                "give the original amount, or the current balance, or the payment and the months remaining",
            )
    elif schedule is not None:
        tolerance = max(5.0, 0.01 * original_amount)
        if balance > schedule + tolerance:
            raise LoanTermsError(
                name("current_balance"),
                f"${balance:,.2f} is above the ${schedule:,.2f} the original schedule leaves after {payments_made} "
                "payments: recheck the original amount, rate, term or origination (a lower balance is a prepaid "
                "loan), or, for a loan behind on its payments, trust the statement's balance with schedule "
                "'statement'",
            )

    if payment is None:
        raise LoanTermsError(
            name("monthly_payment"), "give the term (or the months remaining) or the monthly payment to amortize it"
        )
    if remaining_months is not None and current_balance is not None and monthly_payment is not None:
        required = amortizing_payment(balance, rate_pct, remaining_months)
        if payment < required - max(1.0, 0.005 * required):
            raise LoanTermsError(
                name("monthly_payment"),
                f"${payment:,.2f} does not pay ${balance:,.2f} off in {remaining_months} months "
                f"(that takes ${required:,.2f}; is escrow included?)",
            )

    if term_months is None:
        months = months_to_pay_off(balance, rate_pct, payment)
        if months is None:
            raise LoanTermsError(
                name("monthly_payment"), f"${payment:,.2f} never pays the loan off (below the interest)"
            )
        term_months = (payments_made or 0) + months
    original = original_amount if original_amount is not None else balance
    return LoanTerms(
        original_amount=float(original),
        term_months=int(term_months),
        payments_made=int(payments_made or 0),
        current_balance=float(balance),
        monthly_payment=float(payment),
        origination=origin,
    )


def _resolve_from_statement(
    *,
    rate_pct: float,
    original_amount: float | None,
    term_months: int | None,
    origin: tuple[int, int] | None,
    payments_made: int | None,
    remaining_months: int | None,
    current_balance: float | None,
    monthly_payment: float | None,
    name,
) -> LoanTerms:
    """``schedule="statement"``: amortize the statement's balance (see the module docstring)."""
    if current_balance is None:
        raise LoanTermsError(
            name("current_balance"), 'schedule "statement" amortizes the statement\'s current balance: give it'
        )
    payment = monthly_payment
    if payment is None:
        if remaining_months is not None:
            payment = amortizing_payment(current_balance, rate_pct, remaining_months)
        elif original_amount is not None and term_months is not None:
            payment = amortizing_payment(original_amount, rate_pct, term_months)
        else:
            raise LoanTermsError(
                name("monthly_payment"),
                'schedule "statement" needs the payment, the months remaining, or the original amount and term',
            )
    if remaining_months is not None and monthly_payment is not None:
        required = amortizing_payment(current_balance, rate_pct, remaining_months)
        if payment < required - max(1.0, 0.005 * required):
            raise LoanTermsError(
                name("monthly_payment"),
                f"${payment:,.2f} does not pay ${current_balance:,.2f} off in {remaining_months} months "
                f"(that takes ${required:,.2f})",
            )
    months = remaining_months
    if months is None:
        months = months_to_pay_off(current_balance, rate_pct, payment)
        if months is None:
            raise LoanTermsError(
                name("monthly_payment"), f"${payment:,.2f} never pays the loan off (below the interest)"
            )
    made = payments_made or 0
    return LoanTerms(
        original_amount=float(original_amount if original_amount is not None else current_balance),
        term_months=int(made + months),
        payments_made=int(made),
        current_balance=float(current_balance),
        monthly_payment=float(payment),
        origination=origin,
    )
