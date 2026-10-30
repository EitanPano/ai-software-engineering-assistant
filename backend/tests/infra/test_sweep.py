import pytest

from app.infra.dependency import sweep_lost_runs
from tests.support import recording_logger


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
