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

Trials are yearly: each keeps its model's yearly frame (``LifeModel``'s default ``collect="year"``;
the engine steps monthly, so a 50-year trial runs 600 months). Build trial models with
``collect="month"`` only if you read the monthly rows from the models yourself.

``model_factory`` must be a picklable top-level callable so trials can run in worker processes.
When it is not picklable, the runner transparently falls back to running trials sequentially in the
current process (the simulation is CPU-light, so this is only a speed difference).
"""

import json
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .model import LifeModel, MoneyStat

# A callable that builds a ready-to-run model for a given random seed.
ModelFactory = Callable[[int], LifeModel]


def _money_columns() -> list[str]:
    return [s.title for s in (*LifeModel.STATS, *LifeModel.EXTRA_STATS) if isinstance(s, MoneyStat)]


def _run_trial(args) -> dict:
    """Build and run a single trial, returning its yearly model-vars DataFrame, its seed and its
    deflators (plus its agent frame and events when asked).

    Defined at module scope so it (and its arguments) can be pickled for process-pool execution.
    """
    factory, seed, keep_agent_frames, keep_events = (*args, False, False)[:4]
    model = factory(seed)
    result = model.run()
    trial = {
        "seed": seed,
        "frame": model.datacollector.get_model_vars_dataframe().reset_index(drop=True),
        "deflators": result.deflators,
    }
    if keep_agent_frames:
        trial["agent_frame"] = result.agent_frame
    if keep_events:
        trial["events"] = result.events
    return trial


class MonteCarloResult:
    """Aggregated results of a Monte Carlo study.

    Holds one yearly ``model_vars`` DataFrame per trial (all sharing the same ``Year`` column) and
    provides success-probability, percentile, and fan-chart helpers over them. ``seeds`` are the
    per-trial seeds (rebuild trial ``i`` with ``factory(result.seeds[i])``); ``agent_frames`` and
    ``events`` are kept when the runner was asked to keep them.
    """

    def __init__(
        self,
        frames: list[pd.DataFrame],
        *,
        seeds: "list[int] | None" = None,
        agent_frames: "list[pd.DataFrame] | None" = None,
        events: "list[pd.DataFrame] | None" = None,
        deflators: "list[dict[int, float]] | None" = None,
        real: bool = False,
    ):
        if not frames:
            raise ValueError("MonteCarloResult requires at least one trial frame")
        self.frames = frames
        self.seeds = list(seeds) if seeds is not None else None
        self.agent_frames = agent_frames
        self.events = events
        #: Per-trial cumulative inflation by year (for :meth:`real_dollars`).
        self.deflators = deflators
        #: True when money is in start-year dollars.
        self.real = real

    def real_dollars(self) -> "MonteCarloResult":
        """A copy with every trial's money columns deflated to start-year dollars by that trial's own
        realized inflation (agent frames too; event amounts likewise). Idempotent."""
        if self.real:
            return self
        if self.deflators is None:
            raise ValueError("This result has no per-trial deflators (it was not produced by MonteCarlo.run)")
        money = _money_columns()

        def deflate(frame, deflator, year_column, columns):
            frame = frame.copy()
            factors = frame[year_column].map(lambda y: deflator.get(int(y), 1.0)).astype(float)
            for column in columns:
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce") / factors
            return frame

        return MonteCarloResult(
            [deflate(f, d, "Year", money) for f, d in zip(self.frames, self.deflators, strict=True)],
            seeds=self.seeds,
            agent_frames=None
            if self.agent_frames is None
            else [deflate(f, d, "Year", money) for f, d in zip(self.agent_frames, self.deflators, strict=True)],
            events=None
            if self.events is None
            else [deflate(f, d, "year", ["amount"]) for f, d in zip(self.events, self.deflators, strict=True)],
            deflators=self.deflators,
            real=True,
        )

    @staticmethod
    def _stack(frames: "list[pd.DataFrame]", seeds: "list[int] | None") -> pd.DataFrame:
        parts = []
        for trial, frame in enumerate(frames):
            frame = frame.copy()
            frame.insert(0, "Trial", trial)
            frame.insert(1, "Seed", seeds[trial] if seeds is not None else None)
            parts.append(frame)
        return pd.concat(parts, ignore_index=True)

    def to_parquet(self, directory: "str | os.PathLike") -> Path:
        """Write ``model.parquet`` (every trial stacked, with ``Trial`` and ``Seed`` columns), the agent
        frames and events when kept, and ``meta.json``. Needs pyarrow (the ``parquet`` extra)."""
        from .results import _require_parquet

        _require_parquet()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self._stack(self.frames, self.seeds).to_parquet(directory / "model.parquet", index=False)
        if self.agent_frames is not None:
            self._stack(self.agent_frames, self.seeds).to_parquet(directory / "agents.parquet", index=False)
        if self.events is not None:
            self._stack(self.events, self.seeds).to_parquet(directory / "events.parquet", index=False)
        meta = {
            "seeds": self.seeds,
            "real": self.real,
            "deflators": None
            if self.deflators is None
            else [{str(year): factor for year, factor in d.items()} for d in self.deflators],
        }
        (directory / "meta.json").write_text(json.dumps(meta))
        return directory

    @classmethod
    def load(cls, directory: "str | os.PathLike") -> "MonteCarloResult":
        """Read a result written by :meth:`to_parquet`."""
        from .results import _require_parquet

        _require_parquet()
        directory = Path(directory)
        meta = json.loads((directory / "meta.json").read_text())

        def unstack(name: str) -> "list[pd.DataFrame] | None":
            path = directory / f"{name}.parquet"
            if not path.exists():
                return None
            stacked = pd.read_parquet(path)
            return [
                group.drop(columns=["Trial", "Seed"]).reset_index(drop=True)
                for _, group in stacked.groupby("Trial", sort=True)
            ]

        deflators = meta.get("deflators")
        return cls(
            unstack("model"),
            seeds=meta.get("seeds"),
            agent_frames=unstack("agents"),
            events=unstack("events"),
            deflators=None if deflators is None else [{int(y): f for y, f in d.items()} for d in deflators],
            real=meta.get("real", False),
        )

    @property
    def num_trials(self) -> int:
        return len(self.frames)

    @property
    def years(self) -> list[int]:
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
        keep_agent_frames: Keep every trial's agent frame on the result (keyword-only; memory grows
            with ``n``).
        keep_events: Keep every trial's event table on the result (keyword-only).
    """

    def __init__(
        self,
        model_factory: ModelFactory,
        n: int = 1000,
        seed: int | None = None,
        workers: int | None = None,
        *,
        keep_agent_frames: bool = False,
        keep_events: bool = False,
    ):
        if n < 1:
            raise ValueError("n must be at least 1")
        self.model_factory = model_factory
        self.n = n
        self.seed = seed
        self.workers = workers
        self.keep_agent_frames = keep_agent_frames
        self.keep_events = keep_events

    def _trial_seeds(self) -> list[int]:
        """Derive ``n`` independent, reproducible per-trial seeds from the master seed."""
        sequence = np.random.SeedSequence(self.seed)
        return [int(child.generate_state(1)[0]) for child in sequence.spawn(self.n)]

    def run(self) -> MonteCarloResult:
        """Run all trials and return the aggregated result."""
        seeds = self._trial_seeds()
        args = [(self.model_factory, seed, self.keep_agent_frames, self.keep_events) for seed in seeds]

        if self.workers == 1 or not self._factory_is_picklable():
            trials = [_run_trial(a) for a in args]
        else:
            try:
                with ProcessPoolExecutor(max_workers=self.workers) as executor:
                    trials = list(executor.map(_run_trial, args))
            except Exception:  # noqa: BLE001
                # Fall back to sequential execution if the pool can't run the trials (e.g. an
                # object deep in the model turns out not to be picklable). The sim is CPU-light.
                trials = [_run_trial(a) for a in args]
        return MonteCarloResult(
            [trial["frame"] for trial in trials],
            seeds=[trial["seed"] for trial in trials],
            agent_frames=[trial["agent_frame"] for trial in trials] if self.keep_agent_frames else None,
            events=[trial["events"] for trial in trials] if self.keep_events else None,
            deflators=[trial["deflators"] for trial in trials],
        )

    def _factory_is_picklable(self) -> bool:
        import pickle

        try:
            pickle.dumps(self.model_factory)
            return True
        except Exception:  # noqa: BLE001 - pickling can fail with many exception types
            return False
