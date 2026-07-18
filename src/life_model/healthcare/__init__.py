# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Healthcare, Medicare & long-term-care agents.

These agents are opt-in: they are constructed explicitly (like insurance policies) and registered
in per-type registries. A simulation that constructs none of them is unaffected. Money they charge
flows through ``person.spending.add_expense`` so it participates in the tax unit's year-end
settlement (withdrawal sizing, ``stat_money_spent``) rather than bypassing it.
"""

from .long_term_care import LongTermCare
from .medical_costs import MedicalCosts
from .medicare import Medicare

__all__ = ["MedicalCosts", "Medicare", "LongTermCare"]
