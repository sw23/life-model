# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""life-model: year-step personal-finance simulation built on Mesa agent-based modeling.

The one-call functions take a household spec (a ``HouseholdSpec``, dict, YAML/JSON text or a
path; see ``docs/household-spec.md``) and mirror the ``life-model`` command line::

    import life_model

    result = life_model.run("my-models/household.yaml", seed=1)  # RunResult
    print(life_model.explain(result, 2035))
    life_model.validate("my-models/household.yaml")              # list of findings
    life_model.compare("my-models/household.yaml", sets=["people[alex].retirement_age=62"])
"""

from importlib.metadata import PackageNotFoundError, version

from .account.bank import BankAccount
from .api import compare, explain, reconcile, run, validate
from .economy import EconomyModel
from .model import LifeModel, LifeModelAgent
from .montecarlo import MonteCarlo, MonteCarloResult
from .people.family import Family
from .people.person import GenderAtBirth, MortalityMode, Person, Spending
from .tax.federal import FilingStatus
from .work.job import Job, Salary

try:
    __version__ = version("life-model")
except PackageNotFoundError:  # package is not installed (e.g. source checkout without install)
    __version__ = "0.0.0+dev"

__all__ = [
    "BankAccount",
    "EconomyModel",
    "Family",
    "FilingStatus",
    "GenderAtBirth",
    "Job",
    "LifeModel",
    "LifeModelAgent",
    "MonteCarlo",
    "MonteCarloResult",
    "MortalityMode",
    "Person",
    "Salary",
    "Spending",
    "__version__",
    "compare",
    "explain",
    "reconcile",
    "run",
    "validate",
]
