# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""life-model: year-step personal-finance simulation built on Mesa agent-based modeling."""

from importlib.metadata import PackageNotFoundError, version

from .account.bank import BankAccount
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
    "LifeModel",
    "LifeModelAgent",
    "EconomyModel",
    "MonteCarlo",
    "MonteCarloResult",
    "Person",
    "Family",
    "Spending",
    "GenderAtBirth",
    "MortalityMode",
    "Job",
    "Salary",
    "BankAccount",
    "FilingStatus",
    "__version__",
]
