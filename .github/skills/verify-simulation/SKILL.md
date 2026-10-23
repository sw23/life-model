---
name: verify-simulation
description: Verify that a change to the simulation engine produces correct financial numbers, not just green tests. Use after modifying anything under src/life_model/ that affects money flow (person/family steps, accounts, taxes, loans, insurance, policies, the spec builder), and before committing re-baselined notebook, golden-frame or household-golden outputs.
---

# Verifying simulation changes

Green unit tests are not enough here — most historical bugs (mortgages amortizing for free,
FICA on retirement income, debt double-payment, events firing a year late) passed the then-current
suite. Verify changes by exercising a real simulation, running the invariant checker, and
explaining every number that moved.

## 1. Run a probe simulation under the invariant checker

Prefer a household spec: it builds the household in the canonical order and exercises the same path
users take. Start from a shipped example close to the changed code (`life-model examples`:
`single_renter`, `married_homeowners`, `retiree_couple`, `self_employed`), copy it into the scratchpad
and edit it to hit the change (married couple for settlement changes, retiree for IRA/RMD/Medicare,
homeowner for mortgages, a dated event for event timing):

```bash
.venv/bin/life-model examples --copy retiree_couple <scratchpad>/probe.yaml
.venv/bin/life-model validate <scratchpad>/probe.yaml
.venv/bin/life-model run <scratchpad>/probe.yaml --checks strict --seed 1 --out <scratchpad>/out
.venv/bin/life-model explain <scratchpad>/probe.yaml --year 2030   # each year the change touches
```

For a code path the spec can't reach, write a throwaway script in the scratchpad (not the repo),
using canonical argument names (a `DeprecationWarning` means an old name):

```python
from life_model.model import LifeModel
from life_model.people.person import Person, Spending
from life_model.people.family import Family
from life_model.account.bank import BankAccount
from life_model.work.job import Job, Salary

model = LifeModel(start_year=2026, end_year=2046, checks="strict")
family = Family(model)
p = Person(family=family, name='A', age=40, retirement_age=65,
           spending=Spending(model, base_annual=40000, growth_pct=2))
BankAccount(owner=p, company='Bank', balance=50000, interest_pct=0.5)
Job(owner=p, company='Co', role='Eng', salary=Salary(model, base_annual=100000, raise_pct=3, bonus_pct=0))
result = model.run()
print(result.model_frame[['Year', 'Income', 'Taxes', 'Spending', 'Bank Balance', 'Debt', 'Net Worth']].to_string())
print(result.explain(2030))
```

Remember the silent defaults (AGENTS.md "Known landmines"): `Person` is immortal and files single,
growth defaults to 0%, cash earns 0% and surplus cash is never invested without a `SavingsPolicy`,
taxes settle as a December lump without withholding or estimates.

## 2. Check the invariants

`checks="strict"` / `--checks strict` raises on any violation of the coded invariants
(`life_model/invariants.py`): yearly and monthly money conservation, balance continuity, no negative
balances, no taxable draw while cash sits above the floor, contribution limits, no income after a job
ends, the FICA wage base, RMD minimums, non-negative taxes and the return identities.
`life_model.invariants.check_model(model)` lists violations after the fact; `result.conservation()`
gives the per-year conservation records. A violation is a bug to fix, not a tolerance to widen.

The checker can't judge plausibility, so also check by hand:

- **Sign and magnitude sanity**: taxes are a plausible effective rate for the income (not 0%,
  not >50% for middle incomes); balances don't jump discontinuously except at modeled events.
- **Year and month alignment**: the row for year N reflects year-N flows; a dated event lands in
  its month (`--collect month` / `result.monthly_frame` shows month-end rows), not a year late.
- **No free money**: if a liability shrinks, some account paid for it; if cash arrives, a ledger
  entry explains it (`result.ledger`, `result.events`).

## 3. Compare against the previous behavior

Never use `git stash` for this (an empty stash + pop can drop someone's stashed work). Run the
probe against the base commit in a scratch worktree instead:

```bash
git worktree add <scratchpad>/lm-base <base-commit>
PYTHONPATH=<scratchpad>/lm-base/src .venv/bin/python -m life_model run <scratchpad>/probe.yaml --seed 1 --out <scratchpad>/before --format csv
PYTHONPATH=$PWD/src .venv/bin/python -m life_model run <scratchpad>/probe.yaml --seed 1 --out <scratchpad>/after --format csv
git worktree remove <scratchpad>/lm-base
diff -r <scratchpad>/before <scratchpad>/after
```

`run --json` prints only the summary; the `--out` tables (model frame, ledger, events, returns) are
what to diff. A base commit older than the CLI (pre-#241) needs the Python probe instead.
`life-model compare <spec> --set ...` / `--change patch.yaml` diffs two inputs on the same code; it
does not compare two code versions. Every changed number must be explained by the intended fix, in
the expected direction. An unexplained column moving = investigate before committing.

## 4. Re-baselines (when applicable)

- **Household goldens** (`src/life_model/tests/goldens/households/`) are hand-worked IRS returns and
  must stay green; a tax change that breaks one is wrong unless the golden's worksheet is. If a
  golden's inputs change, regenerate with `python scripts/household_goldens.py` and review the
  `worksheet.md` diff line by line.
- **Generated docs** (`docs/household-spec.md`, `docs/outputs.md`, `docs/constructor-cheatsheet.md`):
  regenerate after changing their sources (see `dev-setup`).
- **`ExampleSimulation.ipynb`**: `jupyter nbconvert --to notebook --execute --inplace
  ExampleSimulation.ipynb` (use the dev-setup venv), then eyeball the final stats table and charts
  against step 2 before committing.

State in the commit message *why* each number moved.

## 5. External spot-checks for financial math

Where a real-world calculator exists, verify against it, not against the old code: loan
amortization (any online amortization schedule), federal tax (IRS tax tables and forms for the
year; `life-model reconcile` lines up a simulated year against a filed return), Social Security PIA
(ssa.gov quick calculator, coarse agreement). Cite the check in the PR/commit description.
