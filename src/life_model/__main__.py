# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""``python -m life_model``: the ``life-model`` command line (see :mod:`life_model.cli`)."""

import sys

from .cli import get_parser, main

__all__ = ["get_parser", "main"]

if __name__ == "__main__":
    sys.exit(main())
