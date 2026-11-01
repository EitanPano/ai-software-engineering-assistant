import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.models.mcp_server.interface import McpServerRecord
from app.models.mcp_server.type import ListedTool, canonical
from app.models.tool_policy.enums import PolicyEffect
from app.services import tool
from app.services.tool import InvalidToolInput

ECHO_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def listed(name: str, schema: dict[str, object] | None = None) -> ListedTool:
    return ListedTool(name=name, description=f"{name} tool", input_schema=schema or ECHO_SCHEMA)


class TestDecide:
    def test_denies_a_tool_that_was_never_registered(self) -> None:
        """No policy row is `None`: the call is denied."""
        assert tool.decide(None) == "deny"

    def test_allows_a_registered_tool_and_only_that_one(self) -> None:
        """Only the `allow` effect passes."""
        assert tool.decide(PolicyEffect.allow) == "allow"
        assert tool.decide(PolicyEffect.deny) == "deny"
        # Plan 011: `ask` waits for a person; plan 010 refused it like `deny`.
        assert tool.decide(PolicyEffect.ask) == "ask"


class TestCanonical:
    """`canonical` must give the form JSONB gives back, or an unchanged tool is never offered."""

    @pytest.mark.parametrize(
        ("sent", "stored"),
        [(1e16, 10**16), (1e22, 10**22), (-1e16, -(10**16)), (-0.0, 0.0), ([1e16], [10**16])],
    )
    def test_a_float_jsonb_rewrites_compares_equal_to_what_it_becomes(
        self, sent: object, stored: object
    ) -> None:
        assert canonical("t", "d", {"n": sent}) == canonical("t", "d", {"n": stored})

    @pytest.mark.parametrize(
        ("a", "b"), [(0, False), (1, True), (1, 1.0), (0, 0.0), (1e15, 10**15), (1e16, 1)]
    )
    def test_values_json_tells_apart_stay_apart(self, a: object, b: object) -> None:
        assert canonical("t", "d", {"n": a}) != canonical("t", "d", {"n": b})


class TestArgumentsDigest:
    def test_is_64_lowercase_hex_characters(self) -> None:
        digest = tool.arguments_digest({"text": "hi"})

        assert len(digest) == 64
        assert digest == digest.lower()
        assert int(digest, 16) >= 0

    def test_does_not_depend_on_key_order(self) -> None:
        assert tool.arguments_digest({"a": 1, "b": [1, {"c": 2, "d": 3}]}) == tool.arguments_digest(
            {"b": [1, {"d": 3, "c": 2}], "a": 1}
        )

    @pytest.mark.parametrize(
        "other", [{"text": "ho"}, {"text": "hi", "x": 1}, {"txt": "hi"}, {"text": "hi "}, {}]
    )
    def test_differs_when_the_arguments_differ(self, other: dict[str, object]) -> None:
        assert tool.arguments_digest(other) != tool.arguments_digest({"text": "hi"})

    def test_reads_non_ascii_text_as_written(self) -> None:
        assert tool.arguments_digest({"text": "é"}) != tool.arguments_digest({"text": "é"})

    def test_is_empty_by_default(self) -> None:
        assert tool.definitions({}) == []
        assert tool.definitions({"lab": []}) == []


class TestNames:
    def test_the_model_sees_server_and_tool_joined_by_two_underscores(self) -> None:
        assert tool.model_name("knowledge", "search") == "knowledge__search"

    def test_splits_at_the_first_separator(self) -> None:
        assert tool.split_name("knowledge__search") == ("knowledge", "search")
        assert tool.split_name("lab__a__b") == ("lab", "a__b")

    @pytest.mark.parametrize("name", ["search", "__search", "knowledge__", "", "__"])
    def test_a_name_without_both_parts_belongs_to_no_server(self, name: str) -> None:
        assert tool.split_name(name) is None


class TestDefinitions:
    def test_are_sorted_by_name_and_strict_on_knowledge_alone(self) -> None:
        # Plan 012: `strict` needs a closed schema and refuses `minimum` and `minLength`, which a
        # third party's definitions use, so it stays on the server we wrote.
        definitions = tool.definitions(
            {"lab": [listed("zeta"), listed("alpha")], "knowledge": [listed("search")]}
        )

        assert [definition["name"] for definition in definitions] == [
            "knowledge__search",
            "lab__alpha",
            "lab__zeta",
        ]
        assert definitions[0]["strict"] is True
        assert all("strict" not in definition for definition in definitions[1:])
        assert all(definition["eager_input_streaming"] is True for definition in definitions)
        assert definitions[0]["description"] == "search tool"
        schema = definitions[0]["input_schema"]
        assert isinstance(schema, dict)
        assert schema["additionalProperties"] is False

    def test_a_third_party_definition_is_sent_as_accepted_with_its_keywords(self) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 1, "x-mcp-header": "n"}},
        }

        definition = tool.definitions({"github": [listed("issue_read", schema)]})[0]

        assert definition["input_schema"] == schema
        assert "strict" not in definition

    def test_are_byte_stable(self) -> None:
        listings = {"lab": [listed("b"), listed("a")]}

        first = json.dumps(tool.definitions(listings))
        second = json.dumps(tool.definitions({"lab": [listed("a"), listed("b")]}))

        assert first == second

    def test_adds_strict_and_streaming_once(self) -> None:
        definition = tool.definitions({"knowledge": [listed("search")]})[0]

        assert list(definition) == [
            "name",
            "description",
            "input_schema",
            "strict",
            "eager_input_streaming",
        ]

    def test_a_third_party_definition_has_no_strict_key(self) -> None:
        definition = tool.definitions({"lab": [listed("echo")]})[0]

        assert list(definition) == ["name", "description", "input_schema", "eager_input_streaming"]


NOW = datetime(2026, 11, 1, tzinfo=UTC)


def server(
    name: str = "lab",
    *,
    pinned: list[ListedTool] | None,
    listing: list[ListedTool] | None = None,
) -> McpServerRecord:
    return McpServerRecord(
        "id", name, "http://lab/mcp", True, listing, NOW, NOW, pinned_tool_definition=pinned
    )


def offered(entry: ListedTool, name: str = "lab__echo") -> dict[str, object]:
    return tool.definitions({"lab": [entry]})[0] | {"name": name}


class TestListingChanges:
    def test_a_name_is_shown_escaped_so_it_cannot_move_a_cursor(self) -> None:
        hostile = "x\x1b[2J\x1b[Hunchanged from the pin"

        (line,) = tool.listing_changes(None, [listed(hostile)])

        assert "\x1b" not in line
        assert line.startswith("added: x")

    def test_a_name_listed_twice_is_a_change_unless_every_copy_matches(self) -> None:
        pin = listed("a")
        other = replace(pin, description="a different one")

        assert tool.listing_changes([pin], [other, pin]) == ["changed: a"]
        assert tool.listing_changes([pin], [pin, pin]) == []


class TestPinHolds:
    """The pin is what an admin accepted: a call runs only while the pin, the last listing and the
    definition the conversation was offered all agree."""

    def test_holds_when_the_listing_and_the_offer_equal_the_pin(self) -> None:
        pin = listed("echo")

        assert tool.pin_holds(server(pinned=[pin], listing=[pin]), "echo", offered(pin))

    def test_knowledge_is_not_pinned_and_always_holds(self) -> None:
        record = server("knowledge", pinned=None)

        assert tool.pin_holds(record, "search", offered(listed("search"), "knowledge__search"))

    def test_an_unpinned_server_never_holds(self) -> None:
        assert not tool.pin_holds(server(pinned=None), "echo", offered(listed("echo")))

    def test_a_tool_the_pin_does_not_name_never_holds(self) -> None:
        pin = listed("echo")

        assert not tool.pin_holds(server(pinned=[pin], listing=[pin]), "other", offered(pin))

    def test_a_changed_listing_description_denies(self) -> None:
        pin = listed("echo")
        changed = replace(pin, description="Do something else.")

        assert not tool.pin_holds(server(pinned=[pin], listing=[changed]), "echo", offered(pin))

    def test_a_changed_listing_schema_denies(self) -> None:
        pin = listed("echo")
        changed = replace(pin, input_schema={"type": "object"})

        assert not tool.pin_holds(server(pinned=[pin], listing=[changed]), "echo", offered(pin))

    @pytest.mark.parametrize(
        ("was", "now"), [(0, False), (1, True), (1, 1.0), (False, 0), (0, 0.0)]
    )
    def test_a_default_that_python_calls_equal_but_json_does_not_denies(
        self, was: object, now: object
    ) -> None:
        schema: dict[str, object] = {"type": "object", "properties": {"n": {"default": was}}}
        pin = listed("echo", schema)
        changed = replace(
            pin, input_schema={"type": "object", "properties": {"n": {"default": now}}}
        )
        assert pin.input_schema == changed.input_schema  # what Python equality would have let by

        assert not tool.pin_holds(server(pinned=[pin], listing=[changed]), "echo", offered(pin))
        assert not tool.pin_holds(server(pinned=[pin], listing=[pin]), "echo", offered(changed))
        assert tool.listing_changes([pin], [changed]) == ["changed: echo"]

    def test_a_tool_gone_from_the_listing_denies(self) -> None:
        pin = listed("echo")

        assert not tool.pin_holds(
            server(pinned=[pin], listing=[listed("other")]), "echo", offered(pin)
        )

    def test_a_conversation_offered_an_older_definition_denies(self) -> None:
        pin = listed("echo")
        older = replace(pin, description="The text before the re-pin.")

        assert not tool.pin_holds(server(pinned=[pin], listing=[pin]), "echo", offered(older))

    def test_a_server_never_listed_holds_on_the_offer_alone(self) -> None:
        # `call_tool` lists again in the call's own session, which catches a change in between.
        pin = listed("echo")

        assert tool.pin_holds(server(pinned=[pin], listing=None), "echo", offered(pin))

    def test_leaves_the_servers_schema_untouched(self) -> None:
        schema: dict[str, object] = {"type": "object", "properties": {}}

        definition = tool.definitions({"lab": [listed("echo", schema)]})[0]

        assert definition["input_schema"] == schema
        assert definition["input_schema"] is not schema


class TestValidateInput:
    def test_returns_the_parsed_input(self) -> None:
        assert tool.validate_input(ECHO_SCHEMA, {"text": "hi"}) == {"text": "hi"}

    def test_names_the_failing_field_and_never_the_value(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {"text": 5, "extra": "secret-value"})

        assert "text" in str(failure.value)
        assert "secret-value" not in str(failure.value)
        assert str(failure.value).startswith("invalid input")

    def test_refuses_an_input_with_unknown_fields(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {"text": "hi", "extra": 1})

        assert "extra" in str(failure.value)

    def test_names_a_missing_required_field(self) -> None:
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(ECHO_SCHEMA, {})

        assert "text" in str(failure.value)

    def test_checks_nested_fields(self) -> None:
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "options": {
                    "type": "object",
                    "properties": {"depth": {"type": "integer", "minimum": 1}},
                    "required": ["depth"],
                }
            },
            "required": ["options"],
        }

        assert tool.validate_input(schema, {"options": {"depth": 2}}) == {"options": {"depth": 2}}
        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(schema, {"options": {"depth": 0}})

        assert "options.depth" in str(failure.value)

    def test_a_remote_reference_is_refused_and_never_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fetched: list[str] = []

        def urlopen(url: str, *args: object, **kwargs: object) -> None:
            fetched.append(url)
            raise OSError("no network in a test")

        monkeypatch.setattr("urllib.request.urlopen", urlopen)
        schema: dict[str, object] = {"$ref": "http://169.254.169.254/latest/meta-data/x.json"}

        with pytest.raises(InvalidToolInput) as failure:
            tool.validate_input(schema, {"text": "hi"})

        assert fetched == []
        assert "169.254" not in str(failure.value)

    def test_a_schema_that_is_itself_invalid_refuses_every_input(self) -> None:
        with pytest.raises(InvalidToolInput):
            tool.validate_input({"type": "no-such-type"}, {"text": "hi"})
