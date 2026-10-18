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

## Task 3 — cash-flow ledger and the conservation check

The conservation check (`life_model.checks`) found these places where money was created or
destroyed without a flow. Each was fixed with a failing test first (`test_ledger.py`,
`TestMoneyConservationBugs`); the symptom column shows the base commit's behaviour.

| # | Bug | Symptom on the base commit | Fix |
| --- | --- | --- | --- |
| 1 | Social Security kept paying a dead person. `SocialSecurity` is not a `Benefit`, so `die()` never removed it. | A single 70-year-old dying at 72 accumulated $117,988 of benefits in a cash pocket nobody owned (`person.cash`), and income ledger entries nobody filed. | `SocialSecurity.pre_step` stops once its person is deceased. |
| 2 | A decedent's carried unpaid-bills debt (`person.debt`) vanished at death: the estate transfer moved accounts, homes and loans but not `debt`. | $49,000 of debt stayed on the dead person; the heir never paid it. | The debt passes to the inheritor (`Person._pass_cash_and_debt_to`) and reduces the taxable estate (IRC §2053). |
| 3 | Cash a decedent held outside any bank account (`person.cash`) vanished at death. | $25,000 stayed with the dead person; the heir got nothing. | The cash passes to the inheritor. |
| 4 | Selling an underwater home (price < mortgage payoff + selling costs) silently wrote the difference off: the mortgage was zeroed and nobody paid. | A $300k sale against a $320k mortgage and $18k of selling costs left the owner's bank at $100,000 (should be $62,000). | `Home.sell` charges the shortfall through the household waterfall (any remainder becomes debt). |
| 5 | Agents removed during a stage still ran the rest of that stage (the engine snapshots the agent list). `die()` removes a decedent's pensions "so nothing of theirs steps again", but a survivor pension still paid the survivor in the year she died. | $10,000 paid to a dead widow's cash pocket. | `LifeModel.step` skips agents removed earlier in the same stage. |
| 6 | With no heir, a decedent's dissolved accounts kept their balances after removal, and their `Donation` kept spending them every year (reported in the `Charity` column). | $3,000 a year of `Charity` from a dead donor's removed account (and the account's balance spent from beyond the grave). | Dissolution (`Person._dissolve_estate`) posts the estate leaving and empties the accounts; `Donation` stops when its donor is dead. |
| 7 | A whole-life policy that ended (death, lapse, expiry) kept its cash value and loan balance: surrendering it later paid the stale cash value out again (money created), and repaying its loan paid off a loan the death benefit or lapse had already settled (money destroyed). | A $16,951 surrender of a policy whose insured had died; a $2,000 repayment of an extinguished loan. | `LifeInsurance.close` settles the policy (cash value and loan to 0); `drop_policy`/`repay_loan` do nothing on an ended policy. |
| 8 | (Crash, not money.) A person who died owning a 529 plan with a living spouse crashed `die()`: the plan's `beneficiary` is the student (a `Child`), which the estate code read as a designated `Person`. | `AttributeError: 'Child' object has no attribute 'is_deceased'`. | Only a `Person` beneficiary counts as a designation (`Person._designated_beneficiary`). |

No existing test's expected value changed.

Output changes no test pinned (base vs. this branch, model frames of the four whole-household
scenarios in `tests/scenarios.py` plus stochastic seeds 1, 5, 11): every pre-existing column is
identical except `Charity` in a stochastic run where a donor died without an heir (bug 6: from the
death year on, the column drops by the $3,000 pledge). `Life Ins Cash Value` on a policy that lapsed
because its loan exceeded its cash value now reads 0 after the lapse (it used to keep the stale
cash value). Runs that hit bug 8 used to crash and now complete.

## Task 4 — typed events

No existing test's expected value changed. `Event("text")` still builds a free-text event (kind
`note`); existing events keep their exact message text and are now typed (`married`, `died`,
`retired`, `retirement_age`, `home_bought`, `home_sold`, `policy_lapsed`, `annuitized`,
`inheritance`, `life_event_fired`). New *detail* events — `forced_sale`, `pretax_withdrawal` (with
the solver's `target`), `withdrawal` (Roth draws by the waterfall), `rmd`, `penalty`,
`shortfall_debt` — are appended to `model.event_log.list` but left out of
`EventLog._repr_html_`, so the notebook's event table is byte-identical to the base commit's
(checked by running the notebook's scenario on both trees). Code that iterates
`event_log.list` sees the extra entries.

## Task 5 — new stats, agent Name/Type/Owner, pre-post snapshot

No existing test's expected value changed. Output changes:

* Model frame: new EXTRA_STATS columns `Net Worth`, `Traditional IRA Balance`, `Roth IRA Balance`,
  `HSA Balance`, `529 Balance`, `Inherited IRA Balance`, `Annuity Balance`, `DAF Balance`,
  `Trust Balance`, `Home Value`, `Home Equity`, `Mortgage Principal`, `AGI`, `Taxable Income`,
  `Marginal Rate` (max across returns), `Standard Deduction Taken` (bool), `Forced Sales`,
  `Pre-tax Withdrawals`. `STATS` (the default `get_yearly_stat_df` columns) is unchanged.
  Balance stats are read at year end by a new `collect_stats` hook that runs after the stages,
  before collection.
* Agent frame: new leading columns `Name`, `Type` and `Owner`, and `Salary` / `Spending Base` (this
  year's base, snapshotted before the `post_step` escalators; reading `Salary.base` at collection
  shows next year's raised value). `add_agent_stat(title, attr, pre_post=True)` snapshots any
  attribute the same way.
* `Spending.person` and `Salary.owner` back-references are set by `Person` and `Job` (reporting
  only).

## Task 6 — RunResult, exports, explain, Monte Carlo

No existing test's expected value changed. `LifeModel.run()` now returns a `RunResult` instead of
`None`; every existing caller (dashboard, RL environment and benchmark, SLM, Monte Carlo, the
notebook, `__main__`, the tests) ignores the return value or steps the model itself, so nothing
else changed. `get_yearly_stat_df` no longer inserts `extra_columns` into the caller's `columns`
list (it used to mutate it) and takes `styled=False` to return the plain DataFrame. The Monte Carlo
runner's private `_run_trial` now returns a dict (frame, seed, deflators, and optionally the agent
frame and events); `MonteCarloResult(frames)` still works positionally.
