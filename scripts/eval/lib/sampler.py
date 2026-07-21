"""可复现的随机采样器。

设计要点：
- 默认 seed 来自 query_ids 排序后的哈希，保证跨机器可复现
- 显式传入 seed 时强制使用，确保 PR/CI 上结果一致
- 至少采样 1 个 query，避免 sample_ratio 过低时返回空集
"""
from __future__ import annotations

import hashlib
import random
from typing import Iterable


class ReproducibleSampler:
    """可复现的随机采样器。"""

    def __init__(self, sample_ratio: float = 0.2, seed: int | None = None):
        if not 0.0 <= sample_ratio <= 1.0:
            raise ValueError(f"sample_ratio 必须在 [0, 1]，实际 {sample_ratio}")
        self.sample_ratio = sample_ratio
        self.seed = seed

    def sample(self, queries: list[dict], key: str = "query_id") -> tuple[list[dict], list[dict], int]:
        """返回 (sampled, not_sampled, seed)。"""
        if not queries:
            return [], [], self.seed or 0

        seed = self.seed
        if seed is None:
            ids_str = "|".join(sorted(str(q[key]) for q in queries))
            seed = int(hashlib.md5(ids_str.encode()).hexdigest()[:8], 16)

        rng = random.Random(seed)
        indices = list(range(len(queries)))
        rng.shuffle(indices)
        n_sample = max(1, int(len(queries) * self.sample_ratio))
        sampled_idx = set(indices[:n_sample])

        sampled = [queries[i] for i in sorted(sampled_idx)]
        not_sampled = [q for i, q in enumerate(queries) if i not in sampled_idx]
        return sampled, not_sampled, seed
