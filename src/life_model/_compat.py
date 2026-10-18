# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Deprecated-alias support for the Plan 27 D8 constructor renames.

Constructors take their canonical keyword names (``owner=``, ``growth_pct=``, ``interest_pct=``,
``*_annual`` / ``*_monthly``) and are keyword-only beyond their first argument (the owner, or the job a
401(k) belongs to). :func:`legacy_signature` keeps the old spellings working for one release: positional
arguments beyond the first and the old keyword names are mapped to the canonical ones with a
``DeprecationWarning`` that names the replacement.
"""

import functools
import warnings
from collections.abc import Callable, Sequence


def legacy_signature(positional: Sequence[str], renames: "dict[str, str] | None" = None, *, first: int = 1) -> Callable:
    """Decorate an ``__init__`` whose parameters after the first ``first`` are keyword-only.

    Args:
        positional: The legacy positional parameter order (old names), including the first ``first``.
        renames: Old keyword name -> canonical name.
        first: How many leading positional arguments the canonical signature still accepts.
    """
    renames = dict(renames or {})

    def decorate(init: Callable) -> Callable:
        cls_name = init.__qualname__.split(".")[0]

        @functools.wraps(init)
        def wrapper(self, *args, **kwargs):
            if len(args) > first:
                extra = args[first:]
                if len(extra) > len(positional) - first:
                    raise TypeError(f"{cls_name}() takes at most {len(positional)} positional arguments")
                names = list(positional[first : first + len(extra)])
                canonical = [renames.get(name, name) for name in names]
                warnings.warn(
                    f"{cls_name}: positional arguments after the first are deprecated; pass "
                    + ", ".join(f"{name}=" for name in canonical)
                    + " by keyword.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                for name, value in zip(canonical, extra, strict=True):
                    if name in kwargs:
                        raise TypeError(f"{cls_name}() got multiple values for argument {name!r}")
                    kwargs[name] = value
                args = args[:first]
            for old, new in renames.items():
                if old in kwargs:
                    if new in kwargs:
                        raise TypeError(f"{cls_name}(): pass {new}= or the deprecated {old}=, not both")
                    warnings.warn(f"{cls_name}({old}=) is deprecated; use {new}=.", DeprecationWarning, stacklevel=2)
                    kwargs[new] = kwargs.pop(old)
            return init(self, *args, **kwargs)

        wrapper.__legacy_renames__ = renames  # type: ignore[attr-defined]
        return wrapper

    return decorate
