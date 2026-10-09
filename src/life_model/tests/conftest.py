# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Suite-wide guards.

Model-level stats are summed only over agents whose class declares them in ``STATS_OWNED``, so a
stat written on an agent type that does not declare it would silently drop out of the totals. The
fixture below makes every such write raise for the duration of the test session, turning the whole
suite into a check that the declarations are complete.
"""

import pytest

from ..model import LifeModel, LifeModelAgent


@pytest.fixture(autouse=True, scope="session")
def _forbid_undeclared_stat_writes():
    stat_names = LifeModel.stat_names()
    original = LifeModelAgent.__setattr__

    def guarded_setattr(self, name, value):
        if name in stat_names and name not in type(self).STATS_OWNED:
            raise AttributeError(
                f"{type(self).__name__} writes model stat {name!r} but does not declare it in STATS_OWNED"
            )
        original(self, name, value)

    LifeModelAgent.__setattr__ = guarded_setattr  # type: ignore[method-assign]
    yield
    LifeModelAgent.__setattr__ = original  # type: ignore[method-assign]
