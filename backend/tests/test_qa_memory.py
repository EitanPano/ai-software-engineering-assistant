"""QA's attacks on long-term memory: hostile ids and cursors, repeated deletes, case-folded
duplicates and the key-shape check at its edges."""

import httpx
import pytest

from app.api.memory import service as memory_service
from app.models.memory.interface import MemoryRecord
from app.services import voyage
from app.services.utils import clock
from app.services.utils.secret_shape import looks_like_secret
from tests.agent_support import bearer
from tests.approval_support import LabBacked
from tests.fake_mcp import mcp_servers as mcp_servers
from tests.knowledge_support import knowledge as knowledge
from tests.memory_support import FACT, remember, stored_memories
from tests.store import store_backed
from tests.support import error_of


@store_backed
@pytest.mark.usefixtures("fakes")
class TestHostileInput(LabBacked):
    @pytest.mark.parametrize(
        "raw_id",
        ["x'%20or%20'1'='1", "%25", "%00", "a" * 3000, "..%2F..%2Fetc"],
    )
    async def test_a_hostile_id_is_a_4xx_and_deletes_nothing(
        self, client: httpx.AsyncClient, raw_id: str
    ) -> None:
        await remember("user-a", FACT)

        res = await client.delete(f"/api/memory/{raw_id}", headers=bearer("user-a"))

        assert res.status_code in (400, 404)
        assert res.json()["requestId"]
        assert len(await stored_memories()) == 1

    async def test_deleting_twice_is_a_204_then_a_404(self, client: httpx.AsyncClient) -> None:
        memory_id = await remember("user-a", FACT)
        headers = bearer("user-a")

        first = await client.delete(f"/api/memory/{memory_id}", headers=headers)
        second = await client.delete(f"/api/memory/{memory_id}", headers=headers)

        assert (first.status_code, second.status_code) == (204, 404)
        assert error_of(second).code == "not_found"

    async def test_another_persons_cursor_leaks_nothing(self, client: httpx.AsyncClient) -> None:
        for n in range(3):
            await remember("user-a", f"A fact {n}.")
        await remember("user-b", "B private fact.")
        page = await client.get("/api/memory?limit=1", headers=bearer("user-a"))
        cursor = page.json()["nextCursor"]

        res = await client.get(f"/api/memory?limit=100&cursor={cursor}", headers=bearer("user-b"))

        assert res.status_code in (200, 400)
        if res.status_code == 200:
            assert all("A fact" not in item["content"] for item in res.json()["items"])

    async def test_a_case_variant_of_a_stored_fact_is_not_stored_again(self) -> None:
        await remember("user-a", "I use Bun.")
        [embedding] = await voyage.embed_documents(["I USE BUN."])
        record = MemoryRecord(
            id="dup-1",
            user_id="user-a",
            conversation_id="c",
            content="I USE BUN.",
            created_at=clock.now(),
        )

        stored = await memory_service.insert_memories([record], [embedding])

        assert stored == 0
        assert len(await stored_memories()) == 1

    async def test_the_same_fact_from_two_people_is_stored_for_each(self) -> None:
        await remember("user-a", FACT)
        await remember("user-b", FACT)

        assert len(await stored_memories()) == 2


class TestSecretShapeEdges:
    @pytest.mark.parametrize(
        "text",
        [
            "My key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV",
            "token ghp_abcdefghijklmnopqrstuvwxyz0123",
            "-----BEGIN RSA PRIVATE KEY-----",
            "aws AKIAIOSFODNN7EXAMPLE",
            "Voyage pa-abcdefghijklmnopqrstuvwxyz",
        ],
    )
    def test_known_key_shapes_are_caught_mid_sentence(self, text: str) -> None:
        assert looks_like_secret(text)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "I keep deploy notes in ops/RUNBOOK.md.",
            "I work on the pgvector-hnsw-halfvec-index-tuning module.",
            "My phone is 0123456789012345678901234567890123.",
        ],
    )
    def test_ordinary_text_is_not_a_secret(self, text: str) -> None:
        assert not looks_like_secret(text)
