from __future__ import annotations

import threading
from typing import Any, Callable


class RequestBudget:
    """Thread-safe request budget and caching controller."""

    def __init__(
        self,
        total_budget: int = 2000,
        category_budgets: dict[str, int] | None = None,
    ):
        self.total_budget = total_budget
        self.consumed = 0
        self.reserved = 0
        self._lock = threading.Lock()
        self.category_budgets = dict(category_budgets or {
            "registry": 500,
            "website": 600,
            "external_footprint": 400,
            "search": 400,
            "reserve": 100,
        })
        self.category_consumed: dict[str, int] = {k: 0 for k in self.category_budgets}
        self.cache: dict[str, Any] = {}
        self.cache_hits = 0

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.total_budget - self.consumed)

    def can_request(self, category: str = "search", cost: int = 1) -> bool:
        with self._lock:
            if self.consumed + cost > self.total_budget:
                return False
            cat_limit = self.category_budgets.get(category)
            if cat_limit is not None:
                cat_used = self.category_consumed.get(category, 0)
                # Allow borrowing from global remaining if category limit reached, provided total remaining > reserve
                if cat_used + cost > cat_limit:
                    reserve = self.category_budgets.get("reserve", 100)
                    if self.total_budget - (self.consumed + cost) < reserve:
                        return False
            return True

    def consume(self, category: str = "search", cost: int = 1) -> bool:
        with self._lock:
            if self.consumed + cost > self.total_budget:
                return False
            cat_limit = self.category_budgets.get(category)
            reserve = self.category_budgets.get("reserve", 100)
            cat_used = self.category_consumed.get(category, 0)
            if cat_limit is not None and cat_used + cost > cat_limit:
                if self.total_budget - (self.consumed + cost) < reserve:
                    return False
            self.consumed += cost
            self.category_consumed[category] = cat_used + cost
            return True

    def get_or_fetch(
        self,
        key: str,
        category: str,
        fetch_fn: Callable[[], tuple[Any, int]],
    ) -> tuple[Any, bool]:
        """Fetch using cache if present; otherwise check budget, fetch, consume, and store.
        fetch_fn returns (result, actual_requests_count).
        Returns (result, was_cached).
        """
        with self._lock:
            if key in self.cache:
                self.cache_hits += 1
                return self.cache[key], True

        if not self.can_request(category, cost=1):
            return None, False

        result, actual_cost = fetch_fn()

        with self._lock:
            self.consumed += actual_cost
            self.category_consumed[category] = self.category_consumed.get(category, 0) + actual_cost
            self.cache[key] = result
            return result, False

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_budget": self.total_budget,
                "consumed": self.consumed,
                "remaining": max(0, self.total_budget - self.consumed),
                "cache_hits": self.cache_hits,
                "cache_size": len(self.cache),
                "category_consumed": dict(self.category_consumed),
                "category_budgets": dict(self.category_budgets),
            }
