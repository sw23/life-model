# Plan 28 re-baseline log

Every existing test whose expected value changed while implementing Plan 28 (explainable outputs:
tax return record, cash-flow ledger, typed events, new stats, `RunResult`) is listed here with its
old value, new value and reason, followed by output changes that no test pins. New tests live in
`test_tax_return.py`, `test_ledger.py`, `test_typed_events.py` and `test_run_result.py`.

## Task 1 — TaxReturn record

No existing test's expected value changed. `compute_taxes` and `TaxUnit.get_income_taxes_due` keep
their intermediates on `TaxesDue`; the totals are computed by the same expressions as before.

## Task 2 — tax stats on every member, Credits and Penalties stats, AGI mislabel

No existing test's expected value changed (every test that reads a member's tax stats uses a
one-person unit, or sums the spouses).

Output changes no test pinned:

* **Per-agent frames of joint returns.** Before, the unit's whole tax bill was recorded on the head
  (the first-constructed spouse) and the other spouse showed 0 in `Taxes`, `Federal Taxes`,
  `State Taxes`, `SS Taxes`, `Medicare Taxes`, `NIIT` and `Itemized Deductions`. Now every member
  carries a share: Social Security and Medicare are each spouse's own payroll tax (the additional
  Medicare tax split by wages), penalties are the spouse's own, and the income taxes (federal
  before penalties, state, NIIT), credits and claimed itemized deductions are split pro rata by each
  spouse's share of the return's income (ordinary plus preferential, negative contributions
  counted as 0; equal shares when nobody had income). One-person units are unchanged.
  **Model-level totals are unchanged** (the shares sum to 1; equal to the return's figures within
  floating-point rounding, ~1e-9 dollars).
* New model columns `Credits` and `Penalties` (EXTRA_STATS). `Federal Taxes` still *includes*
  penalties, as before; `Penalties` is the breakdown, not an addition.
* `compute_taxes`' local `adjusted_gross_income` was renamed: the value was the post-deduction
  taxable income (the `DEFAULT` flat state base on the single-earner wrapper path), never AGI. No
  number changed.
