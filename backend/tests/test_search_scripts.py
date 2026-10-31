"""The two search scripts import and are shaped as their docstrings say. Neither runs here: one is
paid and one empties `app_test`."""

import inspect

from tests import live_retrieval, measure_search


def test_live_retrieval_imports_and_runs_only_as_a_script() -> None:
    assert inspect.iscoroutinefunction(live_retrieval.main)
    assert "PAID" in str(live_retrieval.__doc__)
    assert live_retrieval.TOP == 5


def test_measure_search_imports_and_runs_only_as_a_script() -> None:
    assert inspect.iscoroutinefunction(measure_search.main)
    assert "EMPTIES" in str(measure_search.__doc__)
    assert measure_search.CHUNKS == 100_000
    assert measure_search.BUDGET_SECONDS == 1.0
