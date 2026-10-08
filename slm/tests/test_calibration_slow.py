# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Calibration gate for the adviser's household distribution (slow: Monte Carlo scoring).

Labels only carry signal if households are neither trivially solvent under every lever nor
hopeless under all of them. Before the retirement-income fixes (Social Security, employer match,
starting balances, retirement spending, scenario overlays) 98% of ``pre_retiree`` households had a
best lever solvent in at most half the trials.

``low_earner`` is held to a looser bar: its households are genuinely marginal in this simulator,
chiefly because out-of-pocket medical costs compound at CPI + 2 points for the whole horizon
(``healthcare.medical_inflation_premium``), which roughly triples a 25-year-old's age-85 cost in
real terms. That is a core-config assumption, not something this gate should tune around.
"""

import pytest

from slm.generate_data import DEFAULT_SCENARIOS, generate_examples, solvency_by_scenario

pytestmark = pytest.mark.slow

MAX_SHARE_AT_MOST_HALF = 0.30
MAX_SHARE_AT_MOST_HALF_LOW_EARNER = 0.70
MAX_SHARE_NO_VIABLE = 0.10


def test_household_distribution_is_calibrated():
    examples = generate_examples(list(DEFAULT_SCENARIOS), 12, 12, 20, include_refusals=False, workers=4)
    stats = solvency_by_scenario(examples)
    for scenario, s in stats.items():
        bar = MAX_SHARE_AT_MOST_HALF_LOW_EARNER if scenario == "low_earner" else MAX_SHARE_AT_MOST_HALF
        assert s["share_best_at_most_half"] <= bar, (scenario, s)
        assert s["share_no_viable"] <= MAX_SHARE_NO_VIABLE, (scenario, s)
