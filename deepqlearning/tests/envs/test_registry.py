# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Tests for the environment registry: every name builds, is well-formed, and honors its config."""

import unittest

import numpy as np
from gymnasium.utils.env_checker import check_env

from deepqlearning.envs import registry
from deepqlearning.envs.registry import (
    EnvSpec,
    make_env,
    make_vector_env,
    register_env,
    registered_env_names,
    resolve_env_spec,
)


class TestRegisteredNames(unittest.TestCase):
    def test_every_registered_name_builds(self):
        for name in registered_env_names():
            with self.subTest(name=name):
                env = make_env(name)
                self.assertIsNotNone(env.observation_space)
                self.assertIsNotNone(env.action_space)
                env.close()

    def test_registered_envs_pass_the_gymnasium_env_checker(self):
        for name in ("financial:basic", "financial:mid_career"):
            with self.subTest(name=name):
                check_env(make_env(name), skip_render_check=True)

    def test_bare_financial_name_is_the_basic_scenario(self):
        self.assertEqual(make_env("financial").config["household_scenario"], "basic")

    def test_scenario_names_select_distinct_households(self):
        basic = make_env("financial:basic").config
        high = make_env("financial:high_earner").config
        self.assertNotEqual(basic["initial_salary"], high["initial_salary"])

    def test_unknown_name_is_rejected(self):
        with self.assertRaises(KeyError):
            resolve_env_spec("no_such_env")

    def test_domains_are_tagged(self):
        for name in registered_env_names():
            self.assertEqual(resolve_env_spec(name).domain, "financial")


class TestConfigOverrides(unittest.TestCase):
    def test_config_reaches_the_financial_env(self):
        env = make_env("financial:basic", {"initial_bank_balance": 4321, "reward_preset": "wealth_max"})
        self.assertEqual(env.config["initial_bank_balance"], 4321)
        self.assertEqual(env.config["reward_preset"], "wealth_max")


class TestVectorEnv(unittest.TestCase):
    def test_builds_the_requested_number_of_envs(self):
        venv = make_vector_env("financial", {}, num_envs=3)
        try:
            self.assertEqual(venv.num_envs, 3)
            obs, _ = venv.reset(seed=[0, 1, 2])
            self.assertEqual(np.asarray(obs).shape, (3, 34))
        finally:
            venv.close()

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            make_vector_env("financial", {}, num_envs=1, backend="threads")


class TestOptionalDependencies(unittest.TestCase):
    def test_missing_dependency_names_the_install_hint(self):
        name = "test:needs_missing_dependency"
        register_env(
            EnvSpec(
                name=name,
                factory=lambda config: make_env("financial", config),
                domain="financial",
                requires=("no_such_module_for_registry_test",),
                install_hint="pip install -r requirements-example.txt",
            )
        )
        try:
            with self.assertRaises(ImportError) as ctx:
                make_env(name)
            self.assertIn("no_such_module_for_registry_test", str(ctx.exception))
            self.assertIn("requirements-example.txt", str(ctx.exception))
        finally:
            registry._REGISTRY.pop(name, None)


if __name__ == "__main__":
    unittest.main()
