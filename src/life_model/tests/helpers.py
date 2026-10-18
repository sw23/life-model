# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Helpers for unit tests that drive an agent's monthly stage methods directly (Plan 32)."""

from collections.abc import Callable


def run_months(model, *calls: Callable[[], object], months=range(1, 13)) -> None:
    """Call each of ``calls`` once per month of the model's current year, in order, with
    ``model.month`` (and ``model.period``) set to that month, then restore them.

    A unit test that used to call ``job.pre_step()`` once for a year of pay calls
    ``run_months(model, job.pre_step)`` for the twelve monthly paychecks.
    """
    saved = model.month, model.period
    try:
        for offset, month in enumerate(months):
            model.month = month
            model.period = saved[1] + offset
            for call in calls:
                call()
    finally:
        model.month, model.period = saved
