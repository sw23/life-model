# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Shared medical-inflation deflator for the healthcare agents (Plan 15).

Medical costs, Medicare premiums, and LTC costs all index by cumulative *medical* inflation:
each year compounds ``CPI inflation + healthcare.medical_inflation_premium``. The factor is
cached per model and per year so that N agents over Y years cost O(Y) factor computations
instead of O(N * Y^2).
"""

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from ..model import LifeModel

_CACHE_ATTR = "_medical_inflation_factors"


def medical_inflation_factor(model: "LifeModel", year: int) -> float:
    """Cumulative medical price level from the model start year through ``year``.

    The start year has a factor of 1.0; each subsequent year multiplies by
    ``1 + (CPI inflation + medical_inflation_premium) / 100``. Cached per model+year (safe:
    the economy also caches each year's inflation on first read, so the factor for a given
    year never changes within a run).
    """
    cache: Dict[int, float] = getattr(model, _CACHE_ATTR, None)  # type: ignore[assignment]
    if cache is None:
        cache = {}
        setattr(model, _CACHE_ATTR, cache)
    factor = cache.get(year)
    if factor is None:
        premium = model.config.healthcare.medical_inflation_premium
        # Build up from the nearest cached earlier year to keep the fill linear overall.
        base_year = model.start_year
        factor = 1.0
        for cached_year in cache:
            if base_year < cached_year <= year:
                base_year = cached_year
                factor = cache[cached_year]
        for y in range(base_year, year):
            factor *= 1 + (model.economy.inflation(y) + premium) / 100
        cache[year] = factor
    return factor
