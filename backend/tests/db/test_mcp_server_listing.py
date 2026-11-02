"""The last good listing of a server: written when it changes, not on every run."""

from datetime import UTC, datetime, timedelta

from app.api.mcp_server import service
from app.models.mcp_server.type import ListedTool
from tests.store import reset_store, store_backed

FIRST = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SEARCH = ListedTool("search", "Searches.", {"type": "object", "additionalProperties": False})


async def _updated_at() -> datetime:
    server = await service.find_by_name("knowledge")
    assert server is not None
    return server.updated_at


@store_backed
class TestSaveListing:
    async def test_the_first_listing_is_written(self) -> None:
        await reset_store()

        await service.save_listing("knowledge", [SEARCH], FIRST)

        server = await service.find_by_name("knowledge")
        assert server is not None
        assert server.tool_definition == [SEARCH]
        assert server.updated_at == FIRST

    async def test_the_same_listing_again_touches_nothing(self) -> None:
        await reset_store()
        await service.save_listing("knowledge", [SEARCH], FIRST)

        await service.save_listing("knowledge", [SEARCH], FIRST + timedelta(hours=1))

        assert await _updated_at() == FIRST

    async def test_a_changed_listing_is_written_and_moves_updated_at(self) -> None:
        await reset_store()
        await service.save_listing("knowledge", [SEARCH], FIRST)
        changed = ListedTool("search", "Searches the index.", SEARCH.input_schema)
        later = FIRST + timedelta(hours=1)

        await service.save_listing("knowledge", [changed], later)

        server = await service.find_by_name("knowledge")
        assert server is not None
        assert server.tool_definition == [changed]
        assert server.updated_at == later
