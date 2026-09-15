import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
from norway_company_agent.budget import RequestBudget

def test_request_budget_basic():
    budget = RequestBudget(total_budget=10, category_budgets={"search": 5, "reserve": 2})
    assert budget.remaining == 10
    assert budget.can_request("search", cost=1)
    
    assert budget.consume("search", cost=3)
    assert budget.remaining == 7
    
    # Exceeding category limit but global remaining > reserve allows borrowing
    assert budget.consume("search", cost=3)
    assert budget.remaining == 4
    
    # Consuming past total minus reserve should fail
    assert not budget.consume("search", cost=3) # remaining would be 1 < reserve 2
    assert not budget.can_request("search", cost=3)
    assert budget.remaining == 4

def test_request_budget_cache():
    budget = RequestBudget(total_budget=10)
    calls = 0
    def fetch():
        nonlocal calls
        calls += 1
        return "data", 1

    res1, cached1 = budget.get_or_fetch("key1", "search", fetch)
    assert res1 == "data"
    assert not cached1
    assert calls == 1
    assert budget.consumed == 1

    res2, cached2 = budget.get_or_fetch("key1", "search", fetch)
    assert res2 == "data"
    assert cached2
    assert calls == 1
    assert budget.consumed == 1
    assert budget.cache_hits == 1
