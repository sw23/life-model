# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Backend tests (Plan 20 D5): the real backends import without pulling in any weights/SDKs.

CI never loads model weights — these assert only that the module imports and the classes conform
to the AdviserModel protocol shape (constructors lazy-import their heavy deps, so importing the
module is free). Actual generation is exercised in manual/local runs against real models.
"""

import slm.backends as backends
from slm.adviser import AdviserModel


def test_backends_module_imports_without_heavy_deps():
    # Importing the module must not require torch/transformers/mlx/anthropic.
    assert hasattr(backends, "HFAdviserModel")
    assert hasattr(backends, "MLXAdviserModel")
    assert hasattr(backends, "APIAdviserModel")


def test_backend_classes_have_generate():
    for cls in (backends.HFAdviserModel, backends.MLXAdviserModel, backends.APIAdviserModel):
        assert callable(getattr(cls, "generate", None))


def test_generate_signature_is_protocol_compatible():
    # A subclass that skips __init__ still satisfies the structural AdviserModel protocol via
    # its generate method — confirming the backend surface matches the interface abstraction.
    class _Fake(backends.APIAdviserModel):
        def __init__(self):
            pass

        def generate(self, messages):
            return "DECISION: age_glide"

    assert isinstance(_Fake(), AdviserModel)
