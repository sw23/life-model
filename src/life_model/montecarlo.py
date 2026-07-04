# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Monte Carlo runner for life-model simulations.

Running one simulation answers "what happens under this scenario?"; a Monte Carlo study answers
"how likely is this outcome?" by running many trials that differ only in their random draws (from a
stochastic :class:`~life_model.economy.EconomyModel`, or stochastic mortality) and aggregating the
results.

Usage::

    def build(seed):
        model = LifeModel(seed=seed, scenario="stochastic_economy")
        # ... construct the family, jobs, accounts ...
        return model

    result = MonteCarlo(build, n=1000, seed=42).run()
    result.success_rate(lambda row: row["Bank Balance"] > 0)   # probability of not running out
    result.percentiles("Bank Balance", [10, 50, 90])           # fan-chart frames

``model_factory`` must be a picklable top-level callable so trials can run in worker processes.
When it is not picklable, the runner transparently falls back to running trials sequentially in the
current process (the simulation is CPU-light, so this is only a speed difference).
"""

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, List, Optional, Sequence

import numpy as np
import pandas as pd

from .model import LifeModel

# A callable that builds a ready-to-run model for a given random seed.
ModelFactory = Callable[[int], LifeModel]


def _run_trial(args) -> pd.DataFrame:
    """Build and run a single trial, returning its yearly model-vars DataFrame.

    Defined at module scope so it (and its arguments) can be pickled for process-pool execution.
    """
    factory, seed = args
    model = factory(seed)
    model.run()
    return model.datacollector.get_model_vars_dataframe().reset_index(drop=True)


class MonteCarloResult:
    """Aggregated results of a Monte Carlo study.

    Holds one yearly ``model_vars`` DataFrame per trial (all sharing the same ``Year`` column) and
    provides success-probability, percentile, and fan-chart helpers over them.
    """

    def __init__(self, frames: List[pd.DataFrame]):
        if not frames:
            raise ValueError("MonteCarloResult requires at least one trial frame")
        self.frames = frames

    @property
    def num_trials(self) -> int:
        return len(self.frames)

    @property
    def years(self) -> List[int]:
        """The simulated calendar years (from the first trial; all trials share this range)."""
        return [int(y) for y in self.frames[0]["Year"].tolist()]

    def success_rate(self, predicate: Callable[[pd.Series], bool]) -> float:
        """Fraction of trials for which ``predicate`` is truthy for the final simulated year.

        Args:
            predicate: Receives the last-year row (a :class:`pandas.Series` indexed by stat title,
                e.g. ``row["Bank Balance"]``) and returns a truthy value for a "successful" trial.
        """
        successes = sum(1 for frame in self.frames if predicate(frame.iloc[-1]))
        return successes / self.num_trials

    def _stacked(self, column: str) -> np.ndarray:
        """Return a ``(num_trials, num_years)`` array of ``column`` across all trials."""
        try:
            return np.array([frame[column].to_numpy(dtype=float) for frame in self.frames])
        except KeyError as exc:
            raise KeyError(f"No such stat column {column!r} in the collected trials") from exc

    def percentiles(self, column: str, percentiles: Sequence[float] = (10, 50, 90)) -> pd.DataFrame:
        """Per-year percentiles of ``column`` across trials.

        Returns a DataFrame indexed by year with one column per requested percentile (named
        ``p10``, ``p50``, ...), suitable for plotting a fan chart.
        """
        data = self._stacked(column)
        result = {f"p{int(p)}": np.percentile(data, p, axis=0) for p in percentiles}
        return pd.DataFrame(result, index=pd.Index(self.years, name="Year"))

    def mean(self, column: str) -> pd.Series:
        """Per-year mean of ``column`` across trials."""
        data = self._stacked(column)
        return pd.Series(data.mean(axis=0), index=pd.Index(self.years, name="Year"), name=column)

    def fan_chart(self, column: str, percentiles: Sequence[float] = (10, 50, 90), ax=None):
        """Plot a fan chart of ``column``: the median line with a shaded inter-percentile band.

        Requires matplotlib. Returns the matplotlib Axes.
        """
        import matplotlib.pyplot as plt

        pct = sorted(percentiles)
        frame = self.percentiles(column, pct)
        if ax is None:
            _, ax = plt.subplots()
        years = frame.index
        low, high = f"p{int(pct[0])}", f"p{int(pct[-1])}"
        ax.fill_between(years, frame[low], frame[high], alpha=0.25, label=f"{low}-{high}")
        mid = pct[len(pct) // 2]
        ax.plot(years, frame[f"p{int(mid)}"], label=f"p{int(mid)} (median)")
        ax.set_xlabel("Year")
        ax.set_ylabel(column)
        ax.set_title(f"{column} — {self.num_trials} trials")
        ax.legend()
        return ax


class MonteCarlo:
    """Runs ``n`` independent trials of a model and aggregates them.

    Args:
        model_factory: Picklable top-level callable ``factory(seed) -> LifeModel`` that builds a
            ready-to-run model seeded with the given value. It must fully rebuild the scenario each
            call (models are stateful).
        n: Number of trials.
        seed: Master seed; per-trial seeds are derived deterministically from it via a
            :class:`numpy.random.SeedSequence`, so a run is bit-reproducible under the same master
            seed.
        workers: Process-pool size. ``None`` lets the pool choose; ``1`` forces sequential
            execution in the current process.
    """

    def __init__(
        self,
        model_factory: ModelFactory,
        n: int = 1000,
        seed: Optional[int] = None,
        workers: Optional[int] = None,
    ):
        if n < 1:
            raise ValueError("n must be at least 1")
        self.model_factory = model_factory
        self.n = n
        self.seed = seed
        self.workers = workers

    def _trial_seeds(self) -> List[int]:
        """Derive ``n`` independent, reproducible per-trial seeds from the master seed."""
        sequence = np.random.SeedSequence(self.seed)
        return [int(child.generate_state(1)[0]) for child in sequence.spawn(self.n)]

    def run(self) -> MonteCarloResult:
        """Run all trials and return the aggregated result."""
        seeds = self._trial_seeds()
        args = [(self.model_factory, seed) for seed in seeds]

        if self.workers == 1 or not self._factory_is_picklable():
            frames = [_run_trial(a) for a in args]
        else:
            try:
                with ProcessPoolExecutor(max_workers=self.workers) as executor:
                    frames = list(executor.map(_run_trial, args))
            except Exception:
                # Fall back to sequential execution if the pool can't run the trials (e.g. an
                # object deep in the model turns out not to be picklable). The sim is CPU-light.
                frames = [_run_trial(a) for a in args]
        return MonteCarloResult(frames)

    def _factory_is_picklable(self) -> bool:
        import pickle

        try:
            pickle.dumps(self.model_factory)
            return True
        except Exception:
            return False
