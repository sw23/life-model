# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""life-model: year-step personal-finance simulation built on Mesa agent-based modeling."""

from importlib.metadata import version, PackageNotFoundError

from .model import LifeModel, LifeModelAgent
from .people.person import Person, Spending, GenderAtBirth
from .people.family import Family
from .work.job import Job, Salary
from .account.bank import BankAccount
from .tax.federal import FilingStatus

try:
    __version__ = version("life-model")
except PackageNotFoundError:  # package is not installed (e.g. source checkout without install)
    __version__ = "0.0.0+dev"

__all__ = [
    "LifeModel",
    "LifeModelAgent",
    "Person",
    "Family",
    "Spending",
    "GenderAtBirth",
    "Job",
    "Salary",
    "BankAccount",
    "FilingStatus",
    "__version__",
]
