"""Agent reprs stay short and finite however the agents link to each other."""

import unittest

from ..model import LifeModelAgent
from ..spec import EXAMPLES, build_model, load_example


class TestAgentRepr(unittest.TestCase):
    def test_every_example_agent_has_a_short_repr_naming_its_class_and_id(self):
        for name in EXAMPLES:
            model = build_model(load_example(name))
            for agent in model.agents:
                with self.subTest(example=name, agent=type(agent).__name__):
                    self.assertIsInstance(agent, LifeModelAgent)
                    text = repr(agent)
                    self.assertTrue(text.startswith(f"<{type(agent).__name__} id={agent.unique_id}"), text)
                    self.assertLess(len(text), 200, text)

    def test_a_named_agent_shows_its_name(self):
        model = build_model(load_example(EXAMPLES[0]))
        person = next(iter(model.household.people.values()))
        self.assertEqual(repr(person), f"<Person id={person.unique_id} name={person.name!r}>")


if __name__ == "__main__":
    unittest.main()
