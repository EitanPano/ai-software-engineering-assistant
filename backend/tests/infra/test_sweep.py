from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from app.infra.dependency import sweep_lost_runs, sweep_lost_sources
from app.main import lifespan
from tests.support import recording_logger


class TestTheEntryLifespanSweeps:
    """The sweeps are what V07's "ends interrupted at boot" rests on: deleting either line of
    `main.py`'s lifespan must turn a test red."""

    async def test_runs_both_sweeps_once_the_resources_are_connected_and_before_serving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []

        @asynccontextmanager
        async def resources(app: FastAPI) -> AsyncIterator[None]:
            order.append("connected")
            yield
            order.append("closed")

        async def runs() -> None:
            order.append("sweep runs")

        async def sources() -> None:
            order.append("sweep sources")

        monkeypatch.setattr("app.main.resource_lifespan", lambda: resources)
        monkeypatch.setattr("app.main.sweep_lost_runs", runs)
        monkeypatch.setattr("app.main.sweep_lost_sources", sources)

        async with lifespan(FastAPI()):
            order.append("serving")

        assert order == ["connected", "sweep runs", "sweep sources", "serving", "closed"]


class TestSweepLostSources:
    async def test_runs_the_source_modules_sweep_with_the_boot_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []

        async def fake_sweep(started_before: object) -> int:
            seen.append(started_before)
            return 0

        monkeypatch.setattr("app.api.source.controller.fail_lost_sources", fake_sweep)

        await sweep_lost_sources()

        assert len(seen) == 1

    async def test_a_failed_sweep_is_logged_and_the_boot_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(started_before: object) -> int:
            raise RuntimeError("the database is unreachable")

        monkeypatch.setattr("app.api.source.controller.fail_lost_sources", broken)
        logger, sink = recording_logger()

        await sweep_lost_sources(logger=logger)

        assert any(line.startswith("error lost source sweep failed") for line in sink.lines), (
            sink.lines
        )


class TestSweepLostRuns:
    async def test_runs_the_run_modules_sweep_with_the_boot_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []

        async def fake_sweep(started_before: object) -> int:
            seen.append(started_before)
            return 0

        monkeypatch.setattr("app.api.run.controller.fail_lost_runs", fake_sweep)

        await sweep_lost_runs()

        assert len(seen) == 1

    async def test_a_failed_sweep_is_logged_and_the_boot_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(started_before: object) -> int:
            raise RuntimeError("the database is unreachable")

        monkeypatch.setattr("app.api.run.controller.fail_lost_runs", broken)
        logger, sink = recording_logger()

        await sweep_lost_runs(logger=logger)

        assert any(line.startswith("error lost run sweep failed") for line in sink.lines), (
            sink.lines
        )
