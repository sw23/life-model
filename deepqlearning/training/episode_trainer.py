# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Episode-count training loop over a single environment.

This is the loop to use when the natural budget is "N episodes" rather than "N environment steps":
notebooks, smoke tests, and quick comparisons. :class:`~deepqlearning.training.trainer.Trainer` is
the vectorized, step-budgeted counterpart used for real training runs.

Evaluation here reports mean greedy return and nothing else. Anything domain-specific (how many
episodes ended in bankruptcy, how many in a natural death) is supplied by the caller through the
``eval_summary`` hook, so the loop stays usable for environments that have no such notions.
"""

from typing import Dict, List, Optional

import numpy as np

from ..algos.base import Algorithm
from .rollout import rollout


class EpisodeTrainer:
    """Trains an algorithm for a fixed number of episodes on one environment."""

    def __init__(self, env, algo: Algorithm, config: Optional[Dict] = None):
        self.env = env
        self.algo = algo

        # Training configuration
        self.config = {
            "num_episodes": 1000,
            "save_freq": 100,
            "eval_freq": 50,
            "eval_episodes": 10,
            "print_freq": 10,
            "model_save_path": "model.pt",
            # Base seed for training episodes; each episode uses base_seed + episode for
            # reproducibility. Set to None for nondeterministic training.
            "base_seed": None,
            # Optional callable taking the list of terminal ``info`` dicts from an evaluation
            # round and returning a line to print. Used to attach a domain summary.
            "eval_summary": None,
        }

        if config:
            self.config.update(config)

        self.episode_rewards: List[float] = []
        self.eval_rewards: List[float] = []

    def _episode_seed(self, episode: int) -> Optional[int]:
        base = self.config.get("base_seed")
        return None if base is None else base + episode

    def train(self):
        """Run the episode loop, evaluating and checkpointing at the configured cadences."""
        num_episodes = self.config["num_episodes"]
        print(f"Starting training for {num_episodes} episodes")
        print(f"Environment: {type(self.env).__name__}")
        print(f"Action space size: {self.env.action_space.n}")
        print(f"Observation space: {self.env.observation_space.shape}")

        for episode in range(num_episodes):
            result = rollout(self.env, self.algo, training=True, seed=self._episode_seed(episode))
            self.episode_rewards.append(result.total_reward)
            self.algo.episode_rewards.append(result.total_reward)

            # Advance exploration/entropy schedules once per episode.
            self.algo.anneal(episode / max(1, num_episodes))

            # Print progress
            if episode % self.config["print_freq"] == 0:
                avg_reward = np.mean(self.episode_rewards[-100:])
                print(f"Episode {episode:4d}, Reward: {result.total_reward:8.2f}, Avg Reward (100): {avg_reward:8.2f}")

            # Evaluate agent
            if episode % self.config["eval_freq"] == 0 and episode > 0:
                eval_reward = self._evaluate()
                self.eval_rewards.append(eval_reward)
                print(f"Evaluation at episode {episode}: {eval_reward:.2f}")

            # Save model
            if episode % self.config["save_freq"] == 0 and episode > 0:
                self.algo.save(self.config["model_save_path"])

        # Final save
        self.algo.save(self.config["model_save_path"])
        print("Training completed!")

    def _evaluate(self) -> float:
        """Mean return of greedy episodes on held-out seeds (no exploration, no learning)."""
        eval_rewards = []
        final_infos = []

        for i in range(self.config["eval_episodes"]):
            result = rollout(self.env, self.algo, training=False, seed=self._episode_seed(1_000_000 + i))
            eval_rewards.append(result.total_reward)
            final_infos.append(result.final_info)

        summarize = self.config.get("eval_summary")
        if summarize is not None:
            print(f"  {summarize(final_infos)}")

        return float(np.mean(eval_rewards))

    def get_training_stats(self) -> Dict:
        """Training curves and totals, in a JSON-serializable form."""
        return {
            "episode_rewards": self.episode_rewards,
            "eval_rewards": self.eval_rewards,
            "training_losses": self.algo.training_losses,
            "total_episodes": len(self.episode_rewards),
            "total_steps": self.algo.steps_done,
        }
