"""Small CPU-oriented feature extractors for the two observation layouts."""

import torch
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch import nn


class TopKExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space, features_dim: int = 64):
        super().__init__(observation_space, features_dim)
        self.network = nn.Sequential(
            nn.Linear(observation_space.shape[0], features_dim),
            nn.ReLU(),
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        return self.network(observations)


class PooledSetExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space, features_dim: int = 64, object_hidden: int = 32):
        super().__init__(observation_space, features_dim)
        self.object_network = nn.Sequential(
            nn.Linear(observation_space["objects"].shape[-1], object_hidden),
            nn.ReLU(),
        )
        self.merge = nn.Sequential(
            nn.Linear(observation_space["player"].shape[0] + object_hidden, features_dim),
            nn.ReLU(),
        )

    def forward(self, observations: dict[str, torch.Tensor]) -> torch.Tensor:
        mask = observations["mask"].unsqueeze(-1).bool()
        values = observations["objects"].masked_fill(~mask, 0)
        embedded = self.object_network(values).masked_fill(~mask, 0)
        pooled = embedded.sum(dim=-2) / mask.sum(dim=-2).clamp_min(1)
        return self.merge(torch.cat((observations["player"], pooled), dim=-1))
