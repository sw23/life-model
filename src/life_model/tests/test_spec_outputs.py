# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Plan 28 outputs on the Plan 25 spec examples: money conservation and tax-return identities over
50 years (stochastic economy and mortality included), and the spec on the RunResult."""

import tempfile
import unittest

from ..checks import assert_conservation
from ..results import RunResult
from ..spec import EXAMPLES, build_model, load_example
from ..spec.builder import SpecValidationError, canonical
from .test_tax_return import assert_return_reconciles

#: Seeds per example: the default (the spec's own) plus extra draws for the stochastic examples.
SEEDS = (None, 2, 3)


def _fifty_years(name: str):
    spec = load_example(name)
    return spec.model_copy(update={"meta": spec.meta.model_copy(update={"end_year": spec.meta.start_year + 49})})


def _buildable_examples() -> list[str]:
    names = []
    for name in EXAMPLES:
        try:
            build_model(load_example(name))
        except SpecValidationError:
            continue  # uses a field the engine does not support yet (e.g. self-employment, Plan 31)
        names.append(name)
    return names


class TestSpecExamplesConserveMoney(unittest.TestCase):
    def test_every_buildable_example_for_fifty_years(self):
        names = _buildable_examples()
        self.assertGreaterEqual(len(names), 3)
        stochastic_seen = False
        for name in names:
            spec = _fifty_years(name)
            stochastic = spec.economy is not None and spec.economy.mode == "stochastic"
            mortal = any(person.mortality != "immortal" for person in spec.people)
            stochastic_seen |= stochastic and mortal
            for seed in SEEDS if (stochastic or mortal) else (None,):
                with self.subTest(example=name, seed=seed):
                    model = build_model(spec, seed=seed)
                    result = model.run()
                    self.assertEqual(len(model.balance_sheets), 50)
                    assert_conservation(model)
                    assert_conservation(model, monthly=True)
                    for tax_return in model.tax_returns.values():
                        assert_return_reconciles(self, tax_return)
                    for year in {year for year, _ in model.tax_returns}:
                        taxes = sum(
                            e.amount
                            for e in model.ledger.for_year(year)
                            if e.kind in ("tax", "penalty") and e.sink != "IRS: estate tax"
                        )
                        self.assertAlmostEqual(
                            taxes, sum(r.total_tax for r in model.tax_returns.for_year(year)), places=2
                        )
                    self.assertIs(result.spec, model.household.spec)
                    self.assertEqual(result.spec, canonical(spec))
        self.assertTrue(stochastic_seen, "no example ran a stochastic economy with mortality")


class TestRunResultSpec(unittest.TestCase):
    def test_spec_defaults_to_the_built_household_and_survives_export(self):
        spec = load_example("married_homeowners")
        model = build_model(spec)
        result = model.run()
        # The spec as built (canonical order), i.e. model.household.spec.
        self.assertIs(result.spec, model.household.spec)
        self.assertEqual(result.spec, canonical(spec))
        other = load_example("single_renter")
        self.assertIs(build_model(spec).run(spec=other).spec, other)
        with tempfile.TemporaryDirectory() as directory:
            result.to_json(f"{directory}/run.json")
            result.to_csv(directory)
            loaded = RunResult.load(directory)
        self.assertEqual(loaded.spec, result.spec.model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main()
