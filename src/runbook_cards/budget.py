"""Spend limit. The check runs before every submit: spent so far + the submit's upper bound must fit the budget."""
from __future__ import annotations

import json
import math
from typing import Any


class BudgetError(Exception):
    pass


def usage_cost(usage: dict[str, int], price_in: float, price_out: float) -> float:
    """USD for one usage record at the (non-batch) price per million tokens."""
    return (usage.get("input_tokens", 0) * price_in + usage.get("output_tokens", 0) * price_out) / 1_000_000


def estimate_tokens(body: dict[str, Any]) -> int:
    """Fallback when the provider cannot count: characters / 3, plus a 20 % margin."""
    chars = len(json.dumps(body, ensure_ascii=False, sort_keys=True))
    return math.ceil(chars / 3 * 1.2)


class Budget:
    def __init__(self, limit: float, price_in: float, price_out: float, spent: float = 0.0):
        if not (isinstance(limit, (int, float)) and math.isfinite(limit) and limit > 0):
            raise BudgetError("--budget must be a positive number of USD")
        self.limit = float(limit)
        self.price_in, self.price_out = price_in, price_out
        self.spent = float(spent)

    def bound(self, body: dict[str, Any], input_tokens: int | None) -> float:
        """Upper bound in USD for one request: counted (or estimated) input plus the full max_tokens as output."""
        tin = input_tokens if input_tokens is not None else estimate_tokens(body)
        return usage_cost({"input_tokens": tin, "output_tokens": int(body["max_tokens"])}, self.price_in, self.price_out)

    def allows(self, bound: float) -> bool:
        return self.spent + bound <= self.limit + 1e-12

    def add(self, usage: dict[str, int]) -> None:
        self.spent += usage_cost(usage, self.price_in, self.price_out)
