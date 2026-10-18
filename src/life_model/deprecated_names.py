# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deprecated constructor argument names (Plan 27 D8).

Plan 27 gives the core constructors the spec's canonical argument names: ``owner=`` for the person who
owns the object, ``rate_pct=`` / ``*_pct`` for percentages, ``*_monthly`` / ``*_annual`` for flows. The
old names keep working for one release as deprecated aliases (a ``DeprecationWarning`` names the
replacement), and so do positional arguments after the owner for the constructors that became
keyword-only.
"""

import functools
import warnings
from collections.abc import Callable, Sequence
from typing import Any


def deprecated_arguments(
    renamed: dict[str, str] | None = None,
    *,
    positional: Sequence[str] = (),
    keep_positional: int = 1,
) -> Callable:
    """Decorate a constructor whose arguments were renamed or made keyword-only.

    Args:
        renamed: ``{old name: new name}``; the old keyword is accepted with a ``DeprecationWarning``.
        positional: The constructor's former positional order (new names) after the first
            ``keep_positional`` arguments: extra positional arguments are mapped onto these names with a
            ``DeprecationWarning``.
        keep_positional: How many leading positional arguments stay positional (the owner, or the model).
    """
    renamed = dict(renamed or {})

    def decorate(init: Callable) -> Callable:
        @functools.wraps(init)
        def wrapper(self, *args: Any, **kwargs: Any):
            cls = type(self).__name__
            if len(args) > keep_positional and positional:
                extra = args[keep_positional:]
                if len(extra) > len(positional):
                    raise TypeError(f"{cls}() takes at most {keep_positional + len(positional)} positional arguments")
                names = list(positional[: len(extra)])
                warnings.warn(
                    f"{cls}(): positional arguments after the first {keep_positional} are deprecated; pass "
                    + ", ".join(f"{name}=" for name in names),
                    DeprecationWarning,
                    stacklevel=2,
                )
                for name, value in zip(names, extra, strict=True):
                    if name in kwargs:
                        raise TypeError(f"{cls}() got multiple values for argument {name!r}")
                    kwargs[name] = value
                args = args[:keep_positional]
            for old, new in renamed.items():
                if old in kwargs:
                    if new in kwargs:
                        raise TypeError(f"{cls}() got both {old}= (deprecated) and {new}=")
                    warnings.warn(f"{cls}({old}=) is deprecated; use {new}=", DeprecationWarning, stacklevel=2)
                    kwargs[new] = kwargs.pop(old)
            return init(self, *args, **kwargs)

        wrapper.__deprecated_arguments__ = renamed  # type: ignore[attr-defined]
        return wrapper

    return decorate
