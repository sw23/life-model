# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Name -> environment factory registry.

Every environment the training stack can train on is reachable by a short string name:

* ``financial`` / ``financial:<scenario>`` — the life-model financial environment.

Factories are imported lazily inside the factory call, so importing the registry never pays for
importing ``life_model``. Names that need an optional dependency declare it in
:attr:`EnvSpec.requires`; the dependency is checked at :func:`make_env` time and a missing one
raises a friendly :class:`ImportError` naming what to install.
"""

import importlib.util
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import gymnasium as gym


@dataclass(frozen=True)
class EnvSpec:
    """How to build one registered environment.

    Attributes:
        name: The registered name (``"financial"``, ``"financial:basic"``).
        factory: Builds the environment from a fully merged config dict.
        domain: ``"financial"`` for every built-in environment. Callers use this to decide whether
            financial-only behavior (the evaluation protocol, baseline comparison) applies.
        default_config: Config the caller's overrides are merged on top of.
        requires: Import names of optional dependencies this environment needs.
        install_hint: Command shown when a ``requires`` entry is missing.
    """

    name: str
    factory: Callable[[Dict], gym.Env]
    domain: str
    default_config: Dict = field(default_factory=dict)
    requires: Tuple[str, ...] = ()
    install_hint: str = ""


_REGISTRY: Dict[str, EnvSpec] = {}


def register_env(spec: EnvSpec) -> EnvSpec:
    """Register an environment spec under its name, replacing any previous registration."""
    _REGISTRY[spec.name] = spec
    return spec


def registered_env_names() -> List[str]:
    """Every registered name, sorted."""
    return sorted(_REGISTRY)


def resolve_env_spec(name: str) -> EnvSpec:
    """Look up ``name``. Raises ``KeyError`` if it is not registered."""
    if name in _REGISTRY:
        return _REGISTRY[name]
    known = ", ".join(registered_env_names())
    raise KeyError(f"Unknown environment {name!r}. Registered: {known}")


def _check_requirements(spec: EnvSpec) -> None:
    """Raise a friendly ImportError if any optional dependency of ``spec`` is not installed."""
    missing = [module for module in spec.requires if importlib.util.find_spec(module) is None]
    if missing:
        hint = spec.install_hint or f"pip install {' '.join(missing)}"
        raise ImportError(f"Environment {spec.name!r} needs {', '.join(missing)}. Install with:\n    {hint}")


def make_env(name: str, config: Optional[Dict] = None) -> gym.Env:
    """Build the environment registered as ``name`` with ``config`` merged over its defaults."""
    spec = resolve_env_spec(name)
    _check_requirements(spec)
    merged = dict(spec.default_config)
    merged.update(config or {})
    return spec.factory(merged)


class _EnvFactory:
    """Picklable ``() -> env`` thunk (the async vector backend pickles it into worker processes).

    It holds only the name and config, so the lazy imports inside the factory happen in the worker.
    """

    def __init__(self, name: str, config: Optional[Dict] = None):
        self.name = name
        self.config = dict(config or {})

    def __call__(self) -> gym.Env:
        return make_env(self.name, self.config)


def make_vector_env(
    name: str, config: Optional[Dict] = None, num_envs: int = 1, backend: str = "sync"
) -> gym.vector.VectorEnv:
    """Build a vector env of ``num_envs`` copies of ``name``.

    ``backend="sync"`` steps the copies sequentially in-process (deterministic, the default);
    ``"async"`` runs one worker process per copy.
    """
    spec = resolve_env_spec(name)
    _check_requirements(spec)
    fns = [_EnvFactory(name, config) for _ in range(num_envs)]
    if backend == "async":
        return gym.vector.AsyncVectorEnv(fns)
    if backend != "sync":
        raise ValueError(f"Unknown vector backend {backend!r}; expected 'sync' or 'async'")
    return gym.vector.SyncVectorEnv(fns)


# --- built-in registrations -------------------------------------------------------------------

FINANCIAL_SCENARIOS = ("basic", "high_earner", "low_earner", "mid_career")


def _financial_factory(scenario: str) -> Callable[[Dict], gym.Env]:
    def factory(config: Dict) -> gym.Env:
        from .financial.environment import FinancialLifeEnvGenerator

        return FinancialLifeEnvGenerator.create_scenario_env(scenario, config)

    return factory


for _scenario in FINANCIAL_SCENARIOS:
    register_env(EnvSpec(name=f"financial:{_scenario}", factory=_financial_factory(_scenario), domain="financial"))
register_env(EnvSpec(name="financial", factory=_financial_factory("basic"), domain="financial"))
