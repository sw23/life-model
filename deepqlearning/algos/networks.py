# Copyright 2026 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Network bodies shared by the algorithms.

The financial environment's observation is a flat ``Box(N,)`` vector (``len(OBS_SPEC)`` features), so every network here is
an MLP. The builders
size the network from the observation space alone, so an algorithm never has to know which
environment it is training on.

:class:`MLP` and :class:`DuelingMLP` are the value networks used by DQN. Their submodule attribute
names (``network``, ``feature_layers``, ``value_stream``, ``advantage_stream``) are part of the
checkpoint format — every key in a saved ``state_dict`` is derived from them, so renaming one would
make existing checkpoints unloadable.
"""

import numpy as np
import torch
from gymnasium import spaces
from torch import nn


def _init_linear(module: nn.Module) -> None:
    """Xavier-uniform weights with a small positive bias, applied to every linear layer."""
    if isinstance(module, nn.Linear):
        torch.nn.init.xavier_uniform_(module.weight)
        module.bias.data.fill_(0.01)


class MLP(nn.Module):
    """Plain multi-layer perceptron over a flat state, with dropout between hidden layers."""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: list[int] | None = None):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [512, 256, 128]

        self.state_size = state_size
        self.action_size = action_size

        # Build the network
        layers = []
        input_size = state_size

        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(0.1))
            input_size = hidden_size

        # Output layer
        layers.append(nn.Linear(input_size, action_size))

        self.network = nn.Sequential(*layers)

        # Initialize weights
        self.apply(_init_linear)

    def forward(self, state):
        """Forward pass through the network"""
        return self.network(state)


class DuelingMLP(nn.Module):
    """Dueling architecture: shared features split into a state-value and an advantage stream."""

    def __init__(self, state_size: int, action_size: int, hidden_sizes: list[int] | None = None):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [512, 256]

        self.state_size = state_size
        self.action_size = action_size

        # Shared feature extraction layers
        self.feature_layers = nn.Sequential(
            nn.Linear(state_size, hidden_sizes[0]),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_sizes[0], hidden_sizes[1]),
            nn.ReLU(),
            nn.Dropout(0.1),
        )

        # Value stream
        self.value_stream = nn.Sequential(nn.Linear(hidden_sizes[1], 128), nn.ReLU(), nn.Linear(128, 1))

        # Advantage stream
        self.advantage_stream = nn.Sequential(nn.Linear(hidden_sizes[1], 128), nn.ReLU(), nn.Linear(128, action_size))

        self.apply(_init_linear)

    def forward(self, state):
        features = self.feature_layers(state)

        value = self.value_stream(features)
        advantage = self.advantage_stream(features)

        # Combine value and advantage: Q(s,a) = V(s) + A(s,a) - mean(A(s,a))
        q_value = value + advantage - advantage.mean(dim=1, keepdim=True)

        return q_value


class MLPEncoder(nn.Module):
    """Hidden-layer trunk over a flat state, exposing its output width as ``output_dim``.

    Unlike :class:`MLP` this has no output layer and no dropout: it feeds policy/value heads, and
    dropout inside a policy would make the sampled action distribution differ from the one the
    log-probability was computed under.
    """

    def __init__(self, state_size: int, hidden_sizes: list[int] | None = None):
        super().__init__()
        hidden_sizes = list(hidden_sizes or [64, 64])
        layers: list[nn.Module] = []
        input_size = int(state_size)
        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(input_size, hidden_size))
            layers.append(nn.Tanh())
            input_size = hidden_size
        self.network = nn.Sequential(*layers)
        self.output_dim = input_size
        self.apply(_init_linear)

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return self.network(obs.float())


def build_q_network(
    obs_space: spaces.Space, action_size: int, hidden_sizes: list[int] | None = None, dueling: bool = True
) -> nn.Module:
    """Action-value network over the flattened ``obs_space``.

    Keeps the submodule names existing checkpoints were written with.
    """
    state_size = int(np.prod(obs_space.shape))
    mlp = DuelingMLP if dueling else MLP
    return mlp(state_size, action_size, hidden_sizes)


def build_encoder(obs_space: spaces.Space, hidden_sizes: list[int] | None = None) -> nn.Module:
    """Feature extractor over the flattened ``obs_space``, exposing its width as ``.output_dim``."""
    return MLPEncoder(int(np.prod(obs_space.shape)), hidden_sizes)
