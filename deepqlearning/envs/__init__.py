# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Environment registry and the environments it serves."""

from .registry import EnvSpec, make_env, make_vector_env, register_env, registered_env_names, resolve_env_spec

__all__ = [
    "EnvSpec",
    "make_env",
    "make_vector_env",
    "register_env",
    "registered_env_names",
    "resolve_env_spec",
]
