"""令牌桶限流与配额。

* 每个 API Key 一个令牌桶：容量 = ``burst``，补充速率 = ``rate_limit_per_min / 60``；
* 桶状态保存在进程内存（单实例部署足够；多副本应换 Redis，见 docs/deployment.md）；
* 时间源可注入，便于单元测试不 sleep。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RateDecision:
    allowed: bool
    remaining: float = 0.0
    retry_after: int = 1
    capacity: float = 0.0


@dataclass
class TokenBucket:
    capacity: float
    rate_per_second: float
    tokens: float | None = None
    updated_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = float(self.capacity)

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        if elapsed:
            self.tokens = min(self.capacity, (self.tokens or 0.0) + elapsed * self.rate_per_second)
        self.updated_at = now

    def consume(self, amount: float = 1.0, now: float | None = None) -> RateDecision:
        now = time.monotonic() if now is None else now
        with self.lock:
            self.refill(now)
            if (self.tokens or 0.0) >= amount:
                self.tokens = (self.tokens or 0.0) - amount
                return RateDecision(True, remaining=round(self.tokens, 3), capacity=self.capacity)
            missing = amount - (self.tokens or 0.0)
            wait = missing / self.rate_per_second if self.rate_per_second > 0 else 1.0
            return RateDecision(
                False,
                remaining=round(self.tokens or 0.0, 3),
                retry_after=max(1, int(wait + 0.999)),
                capacity=self.capacity,
            )


class QuotaManager:
    """按 Key 管理令牌桶，并额外维护"最近窗口 QPS"统计。"""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic
        self._hits: dict[str, list[float]] = {}

    def _bucket(self, key_id: str, rate_per_min: int, burst: int) -> TokenBucket:
        bucket = self._buckets.get(key_id)
        if bucket is None:
            capacity = max(1.0, float(burst))
            rate = max(0.001, rate_per_min / 60.0)
            bucket = TokenBucket(capacity=capacity, rate_per_second=rate, updated_at=self._clock())
            self._buckets[key_id] = bucket
        return bucket

    def acquire(self, key_id: str, rate_per_min: int, burst: int, amount: float = 1.0) -> RateDecision:
        """尝试消费一个令牌；超限返回 ``allowed=False`` 与建议重试秒数。"""
        with self._lock:
            bucket = self._bucket(key_id, rate_per_min, burst)
        decision = bucket.consume(amount, now=self._clock())
        if decision.allowed:
            with self._lock:
                window = self._hits.setdefault(key_id, [])
                now = self._clock()
                window.append(now)
                self._hits[key_id] = [item for item in window if now - item <= 60.0]
        return decision

    def qps(self, key_id: str, window_seconds: float = 60.0) -> float:
        """最近窗口内的平均 QPS（用于看板）。"""
        with self._lock:
            window = self._hits.get(key_id, [])
            now = self._clock()
            recent = [item for item in window if now - item <= window_seconds]
            self._hits[key_id] = recent
        return round(len(recent) / window_seconds, 3)

    def reset(self, key_id: str | None = None) -> None:
        """清空桶（Key 轮换/撤销或测试使用）。"""
        with self._lock:
            if key_id is None:
                self._buckets.clear()
                self._hits.clear()
            else:
                self._buckets.pop(key_id, None)
                self._hits.pop(key_id, None)


quota_manager = QuotaManager()
